"""Licencia de nodo: el Central la guarda, las subapps la validan.

En una planta CONTER el `.lic` se emite **por máquina** (el machine code
sale del hardware) y cubre a todas las apps de ese nodo. El Central es su
custodio: lo tiene en disco y lo sirve a quien acredite una service key.
Cada subapp se lo pide y lo **valida ella misma** con `license_core`.

Por qué la subapp valida en vez de creerse un veredicto del Central: un
Central manipulado podría decir "sí" a todo. Verificando la firma Ed25519
en cada proceso, saltarse la puerta exige la clave privada, que no está en
ningún artefacto. El precio es que las subapps empaquetan la cripto; es
una decisión consciente.

Servir el `.lic` por HTTP no lo expone: es un documento **firmado**, no un
secreto. Quien lo copie a otra máquina se encuentra otro machine code.

- `LicenseClient` — el transporte: pide el `.lic` al Central.
- `CentralLicenseGate` — el gate que consume `control_foundation`
  (`LicensingGate`): pide, cachea, valida y decide.
"""

from central_server_app_contract.license.client import (
    LICENSE_API_PREFIX,
    LicenseClient,
    LicenseUnavailable,
)
from central_server_app_contract.license.gate import (
    DEFAULT_REFRESH_SECONDS,
    DEFAULT_RETRIES,
    DEFAULT_RETRY_DELAY_SECONDS,
    NODE_PROFILE,
    CentralLicenseGate,
    LicenseVerdict,
)

__all__ = [
    "CentralLicenseGate",
    "DEFAULT_REFRESH_SECONDS",
    "DEFAULT_RETRIES",
    "DEFAULT_RETRY_DELAY_SECONDS",
    "LICENSE_API_PREFIX",
    "LicenseClient",
    "LicenseUnavailable",
    "LicenseVerdict",
    "NODE_PROFILE",
]
