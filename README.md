# central-server-app-contract

**The CONTER supervisor contract.** This package defines the protocol
between `conter_central_server` and every app it manages — and nothing
else. The generic web chassis it used to ship (auth UI, design system,
settings, wiki, i18n) now lives in
[`control_foundation`](https://github.com/fsebastianrebollar/control_foundation);
apps consume both packages, each for what it owns.

> **Renamed in v0.3.0.** The package was `central-server-app-foundation`
> (import root `central_server_app_foundation`) up to v0.2.0; the repo
> lived at `.../central_server_app_foundation`. Nothing but the name
> changed — update the dependency and rewrite the import root:
>
> ```toml
> "central-server-app-contract @ git+https://github.com/fsebastianrebollar/central_server_app_contract.git"
> ```

> **Still on ≤ v0.1.0?** The last full-chassis release is tagged
> `v0.1.0`. Apps that still import `auth_ui`, `design`, `settings`,
> `settings_ui`, `wiki` or `i18n` must pin that tag — and because that
> tag predates the rename, it still builds the *old* distribution name:
>
> ```toml
> "central-server-app-foundation @ git+https://github.com/fsebastianrebollar/central_server_app_contract.git@v0.1.0"
> ```

## What lives here

| Module | What it is |
|---|---|
| `contract.health` | Blueprint factory for the four contract endpoints: `GET /health`, `GET /version`, `GET /icon`, `POST /shutdown` (bearer token). |
| `contract.cli` | argparse scaffold for the 12 contract flags (`--headless`, `--port`, `--data-dir`, `--prefix`, `--info`, `--auth-url`, …) + preboot handling + `CONTER_*` env propagation. |
| `contract.data_paths` | `CONTER_DATA_DIR` resolver. |
| `version` | Bundled `version.txt` (PyInstaller) + pyproject reader + uptime helper. |
| `auth` | `RemoteUserStore` against the Central's `/api/auth/v1` (contract v1.4), `remote_user_store_from_env()`, and the role taxonomy (`VALID_ROLES`, `can_publish`). |
| `sso` | The `conter_sso` signed cookie: `install_sso_central` (issuer, on the Central) and `install_sso_gate` (subapps), sliding expiry, global logout via `GET /sso/logout`. |
| `license` | Node licence (v1.5): the Central serves the signed `.lic` over `/api/license/v1/current`; each subapp validates it itself with `CentralLicenseGate`. |

## Wiring in a `control_foundation` app

```python
from central_server_app_contract.auth import remote_user_store_from_env
from central_server_app_contract.contract import create_health_blueprint
from central_server_app_contract.sso import install_sso_gate

def flask_factory(ui):
    def gate(app):
        secret = os.environ.get("CONTER_SSO_SECRET", "")
        if secret:
            install_sso_gate(app, secret=secret,
                             central_url=os.environ["CONTER_AUTH_URL"],
                             max_age_seconds=8 * 3600)

    return create_control_app(
        ui, ...,
        blueprints=[create_health_blueprint(...), ...],
        user_store=remote_user_store_from_env(),  # None → local SQLite
        enable_health=False,       # /health is the contract's, not the chassis'
        pre_login_guard=gate,      # SSO gate must run before the login guard
    )
```

The three `create_control_app` parameters used above (`user_store`,
`enable_health`, `pre_login_guard`) exist since `control_foundation`
1.1 (with `auth_options` and `is_supervisor_resolver` joining in 1.2).

## Node licence (v1.5)

A CONTER `.lic` is issued **per machine** (the machine code comes from the
hardware) and covers every app on that node — profile `conter-node`, not
one profile per app. The Central is its custodian: it holds the file and
serves it to anyone presenting a service key. **Each subapp validates it
itself.**

Why validate locally instead of trusting a verdict: a tampered Central
could answer "yes" to everything. Verifying the Ed25519 signature in each
process means bypassing the gate requires the private key, which ships in
no artifact. The price is that subapps bundle the crypto (`license_core`);
that is a deliberate trade.

Serving the `.lic` over HTTP does not expose it — it is a **signed**
document, not a secret. Copied to another machine it meets a different
machine code.

```
GET /api/license/v1/current
Headers: Authorization: Bearer <service-key>
→ 200  {"ok": true, "license": "<.lic text>", "profile": "conter-node"}
→ 404  the Central has no licence installed
→ 401  bad or missing service key
```

```python
import time
from central_server_app_contract.license import (
    CentralLicenseGate, LicenseClient, NODE_PROFILE,
)
from control_foundation.paths import app_data_dir
from license_core import compute_fingerprint, verify_license

# The anchor IS local: it measures the passing of time on THIS machine.
# The `.lic` is not — the Central holds it and serves it over HTTP.
anchor = app_data_dir() / "license" / "time_anchor.dat"
anchor.parent.mkdir(parents=True, exist_ok=True)

def verify(lic_text):
    return verify_license(
        lic_text,
        current_fingerprint=compute_fingerprint(),
        system_now=int(time.time()),
        anchor_path=anchor,
        expected_profile=NODE_PROFILE,
        max_internal_ts=0, max_os_ts=0,     # layers 2 and 3, if the app has them
    )

gate = CentralLicenseGate(
    client=LicenseClient(base_url=os.environ["CONTER_AUTH_URL"],
                         service_key=os.environ["CONTER_AUTH_KEY"]),
    verifier=verify,
    on_giving_up=lambda why: request_shutdown(),          # ordered stop
)
boot_guard = make_license_boot_guard(gate, ...)           # control_foundation
```

The verifier calls `license_core.verify_license` **directly**, and not
`control_foundation`'s `LicenseGate`, on purpose: that gate verifies the
`license.dat` **on disk**, which in the node model never exists locally —
the Central custodies the file. Its equivalent for loose text is private
(`_verify`), so wrapping it would tie the app to an internal detail. If
the chassis ever exposes it, this becomes a one-liner and recovers the
gate's cache and dev/prod toggle.

Four decisions baked into `CentralLicenseGate`:

1. **The subapp validates.** It asks for the `.lic` and checks the
   signature locally.
2. **On boot and every ~100 minutes** (`DEFAULT_REFRESH_SECONDS = 6000`).
   Verifying is expensive and a licence changes once a year. Accepted
   trade-off: an expiring licence stays admitted until the next refresh.
3. **A Central that answers "no licence" is not retried** — insisting
   would not change the answer, and it is no reason to shut down: the
   degraded screen is the right outcome.
4. **A Central that does not answer is retried** (`DEFAULT_RETRIES = 3`,
   one minute apart) before giving up. The Central restarts for ordinary
   reasons — a version upgrade, a port change, the panel's restart button
   — and shutting down on the first failure would turn every restart into
   a plant stoppage. Once the retries are exhausted, `on_giving_up` fires
   **once**; that is where the app wires its ordered shutdown. The gate
   never kills a process itself.

## Contract summary (v1.4)

- **Endpoints**: `GET /health` → `{status, version, uptime_seconds, db}`;
  `GET /version` → `{app, version, built, contract, display_name,
  description}`; `GET /icon` → PNG; `POST /shutdown` (Bearer
  `CONTER_SHUTDOWN_TOKEN`) → clean exit.
- **Preboot**: `--version` and `--info` print and exit without booting
  Flask or touching the DB.
- **Env**: `CONTER_DATA_DIR`, `CONTER_SHUTDOWN_TOKEN`,
  `CONTER_URL_PREFIX`, `CONTER_AUTH_URL`, `CONTER_AUTH_KEY`,
  `CONTER_SSO_SECRET`, `LOG_LEVEL`.
- **Log level**: precedence is flag > `CONTER_LOG_LEVEL` > `LOG_LEVEL`,
  and the canonical tuple is exported as
  `contract.LOG_LEVEL_ENV_VARS` — pass it to the chassis instead of
  writing the literal:

  ```python
  from central_server_app_contract.contract import LOG_LEVEL_ENV_VARS
  from control_foundation.runtime.logging_pref import resolve_cli_level

  level = resolve_cli_level(args.log_level, env_vars=LOG_LEVEL_ENV_VARS)
  setup_logging_from_conf(config_dir(), config_key=..., level=level)
  ```

  `apply_contract_env` exports `LOG_LEVEL` **only when someone asked for a
  level** (the flag on the command line, or one of those variables already
  set). Since v0.5.0: exporting it always made the chassis believe a level
  had been requested on every boot, which left the `.conf`'s `[logging]`
  section decorative — the operator edited it from Settings, saved, and
  nothing happened. That also means the order of these two calls no longer
  matters.
- **Central auth**: subapps launched with `--auth-url`/`--auth-key`
  verify credentials against the Central; with `--sso-secret` the
  shared `conter_sso` cookie replaces the local login.

## Tests

```bash
pip install -e ".[test]"
pytest
```
