"""El gate de licencia de una subapp de planta.

Cumple el protocolo `LicensingGate` de `control_foundation`, así que se le
pasa tal cual a `make_license_boot_guard(...)` y a
`create_licensing_blueprint(...)`.

Las cuatro decisiones que lo definen, todas discutidas:

1. **La subapp valida.** Pide el `.lic` al Central y verifica la firma con
   `license_core`. No se cree un veredicto ajeno.
2. **Cada arranque y cada ~100 minutos.** Verificar es caro (fingerprint
   de hardware, firma, escaneo de artefactos) y una licencia cambia una
   vez al año. La contrapartida, aceptada: una licencia que caduca sigue
   admitida hasta un refresco.
3. **Perfil común de nodo.** El `.lic` cubre la máquina entera, no una
   app: si cada app exigiera el suyo, un nodo necesitaría tres licencias.
4. **Si el Central no responde, se reintenta antes de rendirse.** El
   Central se reinicia por cosas normales —actualizar versión, cambiar el
   puerto, el botón del panel— y durante esos segundos no contesta.
   Apagar al primer fallo convertiría cada reinicio en una parada de
   planta.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from central_server_app_contract.license.client import (
    LicenseClient,
    LicenseUnavailable,
)

logger = logging.getLogger(__name__)

# El perfil que declara el `.lic` de un nodo CONTER. Uno para todas las
# apps de la máquina: la licencia es del nodo, no de la app.
NODE_PROFILE = "conter-node"

DEFAULT_REFRESH_SECONDS = 6000.0
DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY_SECONDS = 60.0


@dataclass(frozen=True)
class LicenseVerdict:
    """Lo que el foundation lee para decidir el arranque."""
    valid: bool
    error_code: str | None = None
    error_message: str | None = None


class CentralLicenseGate:
    """`LicensingGate` que toma la licencia del Central y la valida aquí.

    `on_giving_up` se llama UNA vez, cuando se agotan los reintentos con
    el Central ilocalizable. Es donde la app cablea su apagado ordenado:
    el gate no mata procesos — decir "no hay licencia" y decidir qué hacer
    con eso son responsabilidades distintas.
    """

    def __init__(
        self,
        *,
        client: LicenseClient,
        verifier,
        required: Callable[[], bool] = lambda: True,
        refresh_seconds: float = DEFAULT_REFRESH_SECONDS,
        retries: int = DEFAULT_RETRIES,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
        on_giving_up: Callable[[str], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._verifier = verifier
        self._required = required
        self._refresh_seconds = refresh_seconds
        self._retries = max(1, retries)
        self._retry_delay = retry_delay_seconds
        self._on_giving_up = on_giving_up
        self._sleep = sleep
        self._monotonic = monotonic

        self._lock = threading.Lock()
        self._verdict: LicenseVerdict | None = None
        self._checked_at: float = 0.0
        self._gave_up = False

    # ── protocolo LicensingGate ───────────────────────────────────────

    def is_required(self) -> bool:
        return bool(self._required())

    def runtime_gate(self) -> LicenseVerdict:
        """¿Puede usarse la app? Cacheado: lo llama el middleware web en
        CADA petición, y verificar es caro."""
        if not self.is_required():
            return LicenseVerdict(True, None, "license gate disabled")
        with self._lock:
            fresco = (self._verdict is not None
                      and self._monotonic() - self._checked_at
                      < self._refresh_seconds)
            if fresco:
                return self._verdict
            self._verdict = self._check()
            self._checked_at = self._monotonic()
            return self._verdict

    # ── interno ───────────────────────────────────────────────────────

    def _check(self) -> LicenseVerdict:
        try:
            licencia = self._fetch_with_retries()
        except LicenseUnavailable as exc:
            if exc.reachable:
                # El Central contestó que no hay licencia. No es un fallo
                # de red: reintentar no cambiaría nada y apagar la app no
                # ayuda a nadie — que se vea la pantalla de degradado.
                return LicenseVerdict(False, "LIC_MISSING", str(exc))
            self._give_up(str(exc))
            return LicenseVerdict(False, "LIC_CENTRAL_UNREACHABLE", str(exc))

        estado = self._verifier(licencia)
        if getattr(estado, "valid", False):
            return LicenseVerdict(True)
        return LicenseVerdict(
            False,
            getattr(estado, "error_code", None) or "LIC_INVALID",
            getattr(estado, "error_message", None) or "licencia no válida")

    def _fetch_with_retries(self) -> str:
        """Pide la licencia, tolerando un Central que está reiniciándose.

        Solo se reintenta cuando el Central NO responde. Si responde y
        dice que no hay licencia, insistir no cambia la respuesta.
        """
        ultimo: LicenseUnavailable | None = None
        for intento in range(1, self._retries + 1):
            try:
                licencia = self._client.fetch()
            except LicenseUnavailable as exc:
                if exc.reachable:
                    raise
                ultimo = exc
                logger.warning(
                    "licencia: el Central no responde (intento %d/%d): %s",
                    intento, self._retries, exc)
                if intento < self._retries:
                    self._sleep(self._retry_delay)
                continue
            if intento > 1:
                logger.info("licencia: el Central volvió en el intento %d",
                            intento)
            return licencia
        raise ultimo  # type: ignore[misc]

    def _give_up(self, motivo: str) -> None:
        """Se agotaron los reintentos. Avisa una sola vez."""
        if self._gave_up:
            return
        self._gave_up = True
        logger.error(
            "licencia: el Central sigue sin responder tras %d intentos; "
            "la app no puede seguir funcionando sin licencia validada (%s)",
            self._retries, motivo)
        if self._on_giving_up is not None:
            try:
                self._on_giving_up(motivo)
            except Exception:       # noqa: BLE001
                # Un fallo apagando no puede tumbar al gate: el veredicto
                # ya está decidido y la web tiene que poder contarlo.
                logger.exception("licencia: falló el apagado tras rendirse")
