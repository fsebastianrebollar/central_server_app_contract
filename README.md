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
- **Central auth**: subapps launched with `--auth-url`/`--auth-key`
  verify credentials against the Central; with `--sso-secret` the
  shared `conter_sso` cookie replaces the local login.

## Tests

```bash
pip install -e ".[test]"
pytest
```
