"""Transporte: pedirle el `.lic` del nodo al Central.

Mismo patrón que `RemoteUserStore` — urllib de la stdlib (ni el contrato
ni el foundation ganan dependencias) y TLS sin verificar por defecto,
porque el Central sirve un certificado autofirmado y la llamada es
loopback o LAN de planta.
"""
from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

LICENSE_API_PREFIX = "/api/license/v1"


class LicenseUnavailable(RuntimeError):
    """El Central no ha podido dar la licencia.

    Cubre las dos formas de "no la tengo": el Central no responde (caído,
    reiniciándose) y el Central responde que no tiene licencia instalada.
    Se distinguen por `reachable`, porque la consecuencia es distinta: lo
    primero se reintenta, lo segundo no tiene sentido reintentarlo.
    """

    def __init__(self, mensaje: str, *, reachable: bool):
        super().__init__(mensaje)
        self.reachable = reachable


class LicenseClient:
    """Cliente del API de licencia del Central."""

    def __init__(self, *, base_url: str, service_key: str,
                 timeout: float = 4.0, verify_tls: bool = False) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_key = service_key
        self._timeout = timeout
        if verify_tls:
            self._ssl_context = ssl.create_default_context()
        else:
            self._ssl_context = ssl._create_unverified_context()  # noqa: S323

    def fetch(self) -> str:
        """El texto del `.lic` del nodo.

        Lanza `LicenseUnavailable` si el Central no responde o no tiene
        licencia. No valida nada: de eso se encarga quien la recibe.
        """
        url = f"{self._base_url}{LICENSE_API_PREFIX}/current"
        req = urllib.request.Request(
            url, method="GET",
            headers={"Authorization": f"Bearer {self._service_key}"},
        )
        try:
            with urllib.request.urlopen(
                    req, timeout=self._timeout,
                    context=self._ssl_context) as resp:
                body = json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            # El Central contestó: está vivo, pero no nos da licencia.
            # Reintentar no cambiaría la respuesta.
            raise LicenseUnavailable(
                f"el Central rechazó la petición de licencia (HTTP {e.code})",
                reachable=True) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LicenseUnavailable(
                f"el Central no responde en {self._base_url}: {e}",
                reachable=False) from e

        licencia = (body or {}).get("license") or ""
        if not licencia:
            raise LicenseUnavailable(
                "el Central no tiene licencia instalada", reachable=True)
        return licencia
