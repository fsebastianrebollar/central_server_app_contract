"""El gate de licencia de una subapp de planta.

Todo con dobles: sin `license_core`, sin red y sin relojes reales. Lo que
se prueba son las cuatro decisiones del diseño, no la criptografía —de esa
responde `license_core`, y aquí solo se comprueba que su veredicto se
respeta.
"""

from dataclasses import dataclass

import pytest

from central_server_app_contract.license import (
    CentralLicenseGate,
    LicenseUnavailable,
)


@dataclass
class _Estado:
    """Lo que devuelve `license_core.verify_license` (lo que leemos)."""
    valid: bool
    error_code: str | None = None
    error_message: str | None = None


class _ClienteFalso:
    def __init__(self, *, licencia="LIC-TEXTO", fallos=0, reachable=False):
        self._licencia = licencia
        self._fallos_restantes = fallos
        self._reachable = reachable
        self.llamadas = 0

    def fetch(self):
        self.llamadas += 1
        if self._fallos_restantes > 0:
            self._fallos_restantes -= 1
            raise LicenseUnavailable("central caído",
                                     reachable=self._reachable)
        return self._licencia


def _gate(cliente, *, verifier=None, **kw):
    dormido = []
    reloj = {"t": 0.0}
    gate = CentralLicenseGate(
        client=cliente,
        verifier=verifier or (lambda texto: _Estado(True)),
        retry_delay_seconds=60.0,
        sleep=dormido.append,               # no dormimos de verdad
        monotonic=lambda: reloj["t"],
        **kw,
    )
    return gate, dormido, reloj


# ── El camino feliz ────────────────────────────────────────────────────────

def test_a_valid_licence_lets_the_app_run():
    gate, _, _ = _gate(_ClienteFalso())
    assert gate.runtime_gate().valid is True


def test_the_app_validates_the_licence_itself():
    """No se cree un veredicto del Central: le pasa el texto al verificador
    local. Un Central manipulado no puede decir "sí" por ella."""
    visto = []
    gate, _, _ = _gate(_ClienteFalso(licencia="EL-LIC"),
                       verifier=lambda t: visto.append(t) or _Estado(True))
    gate.runtime_gate()
    assert visto == ["EL-LIC"]


def test_an_invalid_licence_is_reported_with_its_code():
    gate, _, _ = _gate(
        _ClienteFalso(),
        verifier=lambda t: _Estado(False, "LIC_EXPIRED", "caducada"))
    veredicto = gate.runtime_gate()
    assert veredicto.valid is False
    assert veredicto.error_code == "LIC_EXPIRED"


# ── Cada arranque y cada ~100 minutos ──────────────────────────────────────

def test_the_verdict_is_cached_between_refreshes():
    """El middleware web lo llama en CADA petición y verificar es caro."""
    cliente = _ClienteFalso()
    gate, _, reloj = _gate(cliente, refresh_seconds=6000.0)

    for _ in range(50):
        gate.runtime_gate()
    assert cliente.llamadas == 1

    reloj["t"] = 6001.0
    gate.runtime_gate()
    assert cliente.llamadas == 2


def test_a_disabled_gate_never_asks_the_central():
    cliente = _ClienteFalso()
    gate, _, _ = _gate(cliente, required=lambda: False)
    assert gate.runtime_gate().valid is True
    assert cliente.llamadas == 0


# ── El Central que no responde ─────────────────────────────────────────────

def test_a_restarting_central_does_not_stop_the_app():
    """Reiniciar el Central —actualizar versión, cambiar el puerto, el
    botón del panel— lo deja unos segundos sin contestar. Apagar al primer
    fallo convertiría cada reinicio en una parada de planta."""
    apagados = []
    cliente = _ClienteFalso(fallos=1)      # falla una vez y vuelve
    gate, dormido, _ = _gate(cliente, on_giving_up=apagados.append)

    assert gate.runtime_gate().valid is True
    assert cliente.llamadas == 2
    assert dormido == [60.0]               # esperó entre intentos
    assert apagados == []                  # no se apagó nada


def test_it_gives_up_after_the_configured_retries():
    apagados = []
    cliente = _ClienteFalso(fallos=99)
    gate, dormido, _ = _gate(cliente, retries=3, on_giving_up=apagados.append)

    veredicto = gate.runtime_gate()
    assert veredicto.valid is False
    assert veredicto.error_code == "LIC_CENTRAL_UNREACHABLE"
    assert cliente.llamadas == 3
    assert len(dormido) == 2               # no duerme tras el último
    assert len(apagados) == 1


def test_giving_up_notifies_only_once():
    """`on_giving_up` apaga la app: llamarlo en cada request sería pedir el
    apagado cincuenta veces mientras la app aún se está cerrando."""
    apagados = []
    gate, _, reloj = _gate(_ClienteFalso(fallos=99), retries=1,
                           on_giving_up=apagados.append)
    gate.runtime_gate()
    reloj["t"] = 99999.0
    gate.runtime_gate()
    assert len(apagados) == 1


def test_a_failing_shutdown_does_not_break_the_gate():
    """El veredicto ya está decidido; la web tiene que poder contarlo
    aunque el apagado reviente."""
    def _explota(motivo):
        raise RuntimeError("boom")

    gate, _, _ = _gate(_ClienteFalso(fallos=99), retries=1,
                       on_giving_up=_explota)
    assert gate.runtime_gate().error_code == "LIC_CENTRAL_UNREACHABLE"


def test_a_central_without_licence_is_not_retried():
    """Si el Central CONTESTA que no tiene licencia, insistir no cambia la
    respuesta — y no es motivo para apagar la app: que se vea la pantalla
    de degradado."""
    apagados = []
    cliente = _ClienteFalso(fallos=99, reachable=True)
    gate, dormido, _ = _gate(cliente, retries=3, on_giving_up=apagados.append)

    veredicto = gate.runtime_gate()
    assert veredicto.error_code == "LIC_MISSING"
    assert cliente.llamadas == 1           # ni un reintento
    assert dormido == []
    assert apagados == []


# ── El protocolo del foundation ────────────────────────────────────────────

def test_it_satisfies_the_chassis_gate_protocol():
    gate, _, _ = _gate(_ClienteFalso())
    assert hasattr(gate, "runtime_gate") and hasattr(gate, "is_required")
    veredicto = gate.runtime_gate()
    for campo in ("valid", "error_code", "error_message"):
        assert hasattr(veredicto, campo)


def test_it_does_not_expose_the_crypto_only_methods():
    """`import_lic_file` y `current_machine_code` son del que EMITE, no del
    que consume: el blueprint del chasis los detecta con hasattr y responde
    501. Traerlos aquí sería fingir que una subapp activa licencias."""
    gate, _, _ = _gate(_ClienteFalso())
    assert not hasattr(gate, "import_lic_file")
    assert not hasattr(gate, "current_machine_code")
