# Claude context — central_server_app_contract

Onboarding brief for a Claude Code session working on this repo. Read it
before touching code.

---

## What this project is (v0.2.0 — reduced scope)

`central_server_app_contract` is **the CONTER supervisor contract**:
the protocol between `conter_central_server` (portal + process
supervisor running on plant servers) and every app it manages. It is
deliberately small — 13 source files — and everything in it is
CONTER-specific by design.

It used to be a full Flask chassis (auth UI, design system, settings,
wiki, i18n). That generic chassis was vendored into and superseded by
[`control_foundation`](https://github.com/fsebastianrebollar/control_foundation)
(the foundation for controlcore-based apps), and in v0.2.0 this repo
was cut down to the non-overlapping remainder. **Do not add generic
chassis code back here** — if something is useful outside CONTER, it
belongs in `control_foundation`.

**GitHub**: https://github.com/fsebastianrebollar/central_server_app_contract
**Python package name**: `central-server-app-contract`
**Import root**: `central_server_app_contract`
**Version**: `0.3.0` · contract version: **1.4**

The name was `central-server-app-foundation` up to v0.2.0; v0.3.0 renamed
it (repo, distribution and import root) to match what the package
actually became in v0.2.0 — a contract, not a foundation. The rename is
the *only* change in v0.3.0: no code, no contract version bump.

The last full-chassis release is tagged **`v0.1.0`**, which predates the
rename and therefore still builds `central-server-app-foundation` with
the old import root. Apps not yet migrated to `control_foundation` pin
that tag in their pyproject and keep the old imports.

### Layering

```
controlcore            actor runtime (FWObject/ObjectManager)
  └─ control_foundation    generic chassis: runtime+UI+auth+settings+status
       └─ central_server_app_contract   ← THIS: the CONTER protocol
            └─ apps    conter_central_server, conter-stats, ini-configurator
```

### Current consumers

| App | Status |
|---|---|
| conter_central_server | unpinned (tracks the default branch), imports `central_server_app_contract` |
| ini-configurator | unpinned, same; also vendors this repo as a submodule at `libs/central_server_app_contract` |
| conter-stats | pinned `v0.1.0` (full chassis) until migrated to control_foundation — keeps the old `central_server_app_foundation` imports |

## Modules

- `contract/health.py` — factory for the four contract endpoints:
  `GET /health` (`{status, version, uptime_seconds, db}`), `GET
  /version` (`{app, version, built, contract, display_name,
  description}`), `GET /icon`, `POST /shutdown` (Bearer
  `CONTER_SHUTDOWN_TOKEN`, `os._exit(0)` after 200 ms). No token set →
  `/shutdown` is 404 and the supervisor falls back to SIGTERM.
- `contract/cli.py` — `build_parser` (the 12 contract flags),
  `handle_preboot_flags` (`--version`/`--info` print and exit without
  booting Flask), `apply_contract_env` (propagates flags to `CONTER_*`
  env vars), `normalize_prefix`.
- `contract/data_paths.py` — `get_data_dir()` / `override_path()`
  honoring `CONTER_DATA_DIR`.
- `version.py` — `resolve_version` (PyInstaller `version.txt` →
  pyproject → `"dev"`), `resolve_build_date`, `get_uptime_seconds`.
- `auth/remote_store.py` — `RemoteUserStore`: duck type of a local
  user store, backed by the Central's `/api/auth/v1` (urllib, Bearer
  service key, TLS unverified by default — self-signed cert on plant
  LAN). Writes that would fork the user base raise `ValueError`.
- `auth/factory.py` — `remote_user_store_from_env()`: returns a
  `RemoteUserStore` when `CONTER_AUTH_URL` is set, else `None` (caller
  keeps its local store; in `control_foundation`,
  `create_control_app(user_store=None)` builds the local SQLite one).
- `auth/roles.py` — `VALID_ROLES = ("operator", "supervisor",
  "admin")`, `can_publish`. Contract vocabulary: these strings travel
  in API responses and the SSO cookie.
- `sso/token.py` — `conter_sso` cookie: `issue_token` /
  `validate_token` (itsdangerous, salt `conter-sso-v1`).
- `sso/integration.py` — `install_sso_central` (issuer, on the
  Central) and `install_sso_gate` (subapps: cookie is the source of
  truth, `/login` redirects to the Central, sliding expiry, logout via
  `<central>/sso/logout`). Relies on cookies ignoring the port: all
  apps share the host.

## Wiring into a control_foundation app

`create_control_app` grew three hooks for this package
(`feat/conter-integration-hooks`): `user_store=` (inject the
`RemoteUserStore`), `enable_health=False` (free `/health` for the
contract blueprint), `pre_login_guard=` (install `install_sso_gate`
**before** the login guard — from `on_ready` it would run too late).
See README for the canonical snippet.

## Conventions

- Keyword-only constructor/factory params; docstrings explain the *why*.
- stdlib transport (urllib) in `remote_store` — no requests dependency.
- Tests: `pytest` (`pip install -e ".[test]"`); a fake threaded HTTP
  server stands in for the Central in `tests/test_remote_store.py`.
- Every module keeps its own test file under `tests/`.
