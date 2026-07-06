# Claude context — central_server_app_foundation

This document is the onboarding brief for a new Claude Code session working on the
`central_server_app_foundation` project. Read it entirely before touching any code.

---

## What this project is

`central_server_app_foundation` is a reusable Flask chassis library extracted from
`conter-stats` (a factory-floor test results dashboard). It packages all the
scaffolding that every internal Conter app needs — supervisor contract, auth, wiki,
settings, design system, i18n — so individual apps only implement their domain logic.

**GitHub**: https://github.com/fsebastianrebollar/central_server_app_foundation
**Python package name**: `central-server-app-foundation`
**Import root**: `central_server_app_foundation`
**Version**: `0.1.0`

### Current consumers

| App | Repo | What it uses from the chassis |
|---|---|---|
| conter-stats | github.com/fsebastianrebollar/conter-stats | all modules |
| ini-configurator | github.com/fsebastianrebollar/ini-configurator | i18n |

Install for development:

```bash
git clone https://github.com/fsebastianrebollar/central_server_app_foundation.git
cd central_server_app_foundation
pip install -e ".[test]"
python -m pytest tests/ -q
```

---

## Origin and history

The library was extracted from `conter-stats` in ten phases over the branch
`feat/monorepo-app-base` using `git filter-repo`. The commit history reflects the
incremental extraction — each commit brought one module across:

1. `contract.health` — /health /version /icon /shutdown blueprint factory
2. `contract.cli` — argparse scaffold for 9 standard flags
3. `contract.data_paths` — CONTER_DATA_DIR resolver
4. `version` — bundled-file + pyproject reader + uptime
5. `auth` — UserStore (SQLite + roles + bootstrap admin)
6. `wiki` — WikiStore + markdown renderer
7. `settings` — SettingsStore (two-scope SQLite key/value)
8. `design` — chassis base.html + Sidebar API + chassis.js + pill toolbar + settings shell + auth UI (sub-commits 8a–8d)
9. `i18n` — Babel wiring + merged es/de catalogs
10. Renamed `conter_app_base` → `central_server_app_foundation`, extracted to own repo

The history preserves why each design decision was made; `git log --follow` is useful
when something looks unusual.

---

## Project layout

```
central_server_app_foundation/
├── __init__.py                         # package root, version = "0.1.0"
├── version.py                          # get_version / get_build_date / get_uptime_seconds
├── contract/
│   ├── __init__.py                     # re-exports from the three submodules
│   ├── health.py                       # create_health_blueprint() factory
│   ├── cli.py                          # build_parser / handle_preboot_flags / apply_contract_env
│   └── data_paths.py                   # get_data_dir / override_path
├── auth/
│   ├── __init__.py                     # exports UserStore, RemoteUserStore, make_user_store, VALID_ROLES, can_publish
│   ├── user_store.py                   # SQLite user store (is_remote = False)
│   ├── remote_store.py                 # RemoteUserStore — same interface, backed by Conter Central /api/auth/v1 (urllib, bearer key)
│   └── factory.py                      # make_user_store() — RemoteUserStore if CONTER_AUTH_URL set, else UserStore
├── sso/
│   ├── __init__.py                     # exports SSO_COOKIE_NAME, issue_token, validate_token, install_sso_central, install_sso_gate
│   ├── token.py                        # signed conter_sso token (itsdangerous, salt conter-sso-v1)
│   └── integration.py                  # install_sso_central (issuer: cookie mirrors session, /sso/logout) + install_sso_gate (subapp: cookie is identity source, redirects to Central login, intercepts login/logout, sliding refresh)
├── auth_ui/
│   ├── __init__.py                     # exports create_auth_blueprint
│   ├── blueprint.py                    # 16-route Flask blueprint factory
│   └── templates/central_server_app_foundation/auth/
│       ├── login.html                  # standalone login page
│       ├── user.html                   # default user page (extends base.html)
│       ├── _user_body.html             # profile + modals partial
│       └── _user_scripts.html          # modal JS partial
├── design/
│   ├── __init__.py                     # exports Sidebar, SidebarEntry, create_design_blueprint
│   ├── blueprint.py                    # design blueprint factory
│   ├── sidebar.py                      # SidebarEntry dataclass
│   ├── static/
│   │   ├── chassis.js                  # theme toggle + sidebar drawer + ESC
│   │   ├── pill-toolbar.js             # floating pill toolbar component
│   │   └── pill-toolbar.css
│   └── templates/central_server_app_foundation/design/
│       ├── base.html                   # chassis base template (all apps extend this)
│       └── _sidebar.html               # nav partial
├── settings/
│   ├── __init__.py                     # exports SettingsStore
│   └── store.py                        # two-scope SQLite key/value store
├── settings_ui/
│   ├── __init__.py                     # exports SettingsShell/Section/Button, create_settings_blueprint
│   ├── blueprint.py                    # settings blueprint factory
│   ├── sections.py                     # SettingsShell / SettingsSection / SettingsButton dataclasses
│   ├── static/settings.css             # section grid + button-cluster CSS
│   └── templates/central_server_app_foundation/settings/
│       └── _sections.html              # settings grid partial
├── wiki/
│   ├── __init__.py                     # exports WikiStore, render_markdown, utils
│   ├── store.py                        # SQLite wiki page tree
│   ├── markdown.py                     # python-markdown renderer
│   └── utils.py                        # slugify, role_rank, safe_upload_name, user_can_see
└── i18n/
    ├── __init__.py                     # exports init_babel, make_locale_resolver, DEFAULT_SUPPORTED_LANGUAGES
    ├── babel.py                        # Flask-Babel wiring
    ├── babel.cfg                       # pybabel extraction config
    └── translations/
        ├── messages.pot
        ├── es/LC_MESSAGES/messages.{po,mo}
        └── de/LC_MESSAGES/messages.{po,mo}

tests/
    test_auth.py
    test_auth_ui.py
    test_cli.py
    test_data_paths.py
    test_design.py
    test_health_blueprint.py
    test_i18n.py
    test_settings.py
    test_settings_ui.py
    test_version.py
    test_wiki.py
```

---

## Module reference

### `contract.health` — Supervisor contract endpoints

```python
from central_server_app_foundation.contract import create_health_blueprint

health_bp = create_health_blueprint(
    app_name="my-app",
    display_name="My App",
    description="Does things.",
    contract_version="1.3",
    get_version=lambda: "1.0.0",
    get_build_date=lambda: "2025-01-01",
    get_uptime_seconds=lambda: 42.0,
    db_probe=lambda: True,           # callable → bool, or None to skip
    icon_path="app/static/img/logo-256.png",
    shutdown_token_env="CONTER_SHUTDOWN_TOKEN",
)
app.register_blueprint(health_bp)
```

Mounts four endpoints: `GET /health`, `GET /version`, `GET /icon`, `POST /shutdown`.
All are auth-bypassed (caller must add them to the public endpoints list).

`/health` probes the DB with a **fresh connection** (not the pool) with 2 s timeout so
a down DB cannot stall the supervisor's polling loop.

`/shutdown` only exists when `CONTER_SHUTDOWN_TOKEN` env var is set; returns 404
otherwise (contract v1.3 fallback to SIGTERM).

---

### `contract.cli` — Argparse scaffold

```python
from central_server_app_foundation.contract import (
    build_parser, handle_preboot_flags, apply_contract_env,
)

parser = build_parser(description="My App — Web & Desktop")
parser.add_argument("--my-flag", ...)   # add app-specific flags
args = parser.parse_args()

handle_preboot_flags(args, get_version=..., app_name=..., ...)   # handles --version/--info
apply_contract_env(args)   # propagates flags → CONTER_* env vars
```

Standard flags declared by the chassis (do NOT re-declare in apps):
`--headless`, `--host`, `--port`, `--log-level`, `--data-dir`,
`--shutdown-token`, `--prefix`, `--info`, `--version`.

`handle_preboot_flags` handles `--version` (print + exit) and `--info`
(print JSON metadata + exit, no Flask boot).

`apply_contract_env` sets `CONTER_DATA_DIR`, `CONTER_SHUTDOWN_TOKEN`,
`CONTER_URL_PREFIX`, `CONTER_LOG_LEVEL`, `LOG_LEVEL` before `create_app()` is called.

---

### `contract.data_paths` — Data directory resolver

```python
from central_server_app_foundation.contract import get_data_dir, override_path

base = get_data_dir()           # returns CONTER_DATA_DIR or None
path = override_path("cache")   # returns base/cache (creates dir) or None
```

`override_path` returns `None` when no override is set, meaning services fall back to
their legacy default path. This is **opt-in** — existing apps have zero regression
when `--data-dir` is omitted.

---

### `version` — Version helpers

```python
from central_server_app_foundation.version import (
    get_version,         # bundled version.txt → pyproject.toml → "dev"
    get_build_date,      # bundled build_date.txt → "dev"
    get_uptime_seconds,  # seconds since module import (_START_TIME captured at import)
)
```

Works in both frozen PyInstaller builds and source runs. The app declares its own
`APP_NAME`, `APP_DISPLAY_NAME`, `APP_DESCRIPTION`, `CONTRACT_VERSION` constants and
passes them to `create_health_blueprint` and `handle_preboot_flags`.

---

### `auth` — User store

```python
from central_server_app_foundation.auth import UserStore, VALID_ROLES, can_publish

store = UserStore(
    db_path="auth.db",                    # str or callable () → str (late binding for tests)
    translator=_,                         # optional gettext callable
    bootstrap_admin="admin",
    bootstrap_password="changeme",
)

store.init_schema()
store.authenticate("username", "password")   # → user dict or None
store.create_user("username", "password")
store.set_role("username", "supervisor")
store.list_users()
store.delete_user("username")
store.change_password("username", "newpass")
store.valid_roles    # → ("operator", "supervisor", "admin")
```

**Roles**: `operator` (default) < `supervisor` (can publish) < `admin` (full).
`can_publish(role)` returns True for supervisor and admin.

Bootstrap admin is created on first `init_schema()` call if no users exist.
Password is hashed with `werkzeug.security.generate_password_hash`.

---

### `auth_ui` — Auth blueprint factory

```python
from central_server_app_foundation.auth_ui import create_auth_blueprint

auth_bp = create_auth_blueprint(
    user_store=store,
    post_login_endpoint="main.dashboard",
    gettext=_,
    supported_languages=("en", "es", "de"),
    allow_guest=True,
    get_user_pref=get_user_pref,          # (username, key, default) → value
    set_user_pref=set_user_pref,          # (username, key, value) → None
    on_login_hook=_on_login,              # (user_dict, session) → None, called after login
    login_brand_short="CS",
    login_brand_full="Conter Stats",
    login_stylesheet_urls=(("static", "css/app.css"),),    # OPTIONAL: only for extra app CSS
    login_favicon_url=("static", "img/favicon.ico"),
    user_template="user.html",            # app can override (must include partials)
    protected_user="conter",              # username that cannot be deleted/role-changed
)
app.register_blueprint(auth_bp)
```

Mounts 16 routes under the `auth` blueprint name (so existing `url_for("auth.login")`
calls work unchanged).

**Template customisation**: The library ships a default `user.html` that extends
`base.html`. Apps that want custom chrome keep their own `user.html` and
`{% include "central_server_app_foundation/auth/_user_body.html" %}` +
`{% include "central_server_app_foundation/auth/_user_scripts.html" %}`.

**`login.html` CSS auto-wiring**: `login.html` is a standalone template (does NOT
extend `base.html`) so it must load its own CSS. Since v0.1.1, the auth blueprint
auto-detects the design blueprint and injects `auth_chassis_css_url` into the template
context — `login.html` loads chassis `style.css` automatically whenever the design
blueprint is registered. Apps do NOT need to pass `login_stylesheet_urls` for the
chassis CSS; that parameter is only needed for **additional** app-specific stylesheets.

`login_stylesheet_urls` and `login_favicon_url` accept either plain strings or
`(endpoint, filename)` tuples that resolve via `url_for` at request time — required
for v1.3 reverse-proxy deployments where `APPLICATION_ROOT` shifts all URLs.

---

### `design` — Chassis base template + Sidebar

```python
from central_server_app_foundation.design import Sidebar, create_design_blueprint

sidebar = Sidebar()
sidebar.entry("Dashboard", "main.dashboard", "grid-2x2")
sidebar.entry("Settings", "main.settings", "settings", admin_only=True)
sidebar.entry("Wiki", "wiki.index", "book")
sidebar.entry("Reports", "main.reports", "chart-bar",
              active_endpoints=("main.reports_daily", "main.reports_monthly"))

design_bp = create_design_blueprint(
    sidebar=sidebar,
    brand_name="Conter Stats",
    theme_save_url="/api/theme",
    supported_languages=("en", "es", "de"),
    get_user=lambda: session.get("user_id"),
    get_role=lambda: session.get("role", "operator"),
    get_theme=lambda: session.get("theme", ""),
    get_lang=lambda: session.get("lang", "en"),
    is_guest=lambda: session.get("is_guest", False),
)
app.register_blueprint(design_bp)
```

Apps extend `central_server_app_foundation/design/base.html` and override blocks:
`title`, `header_extra_widgets`, `pre_scripts`, `content`, `scripts`.

The `base.html` automatically loads `chassis.js` (theme + sidebar + ESC) and
`settings.css` (from the settings_ui blueprint's static URL).

**Sidebar role gating**: `admin_only=True` hides tab for non-admins.
`supervisor_only=True` hides tab for operators and guests.
`hide_for_guests=True` hides tab for guest sessions.
`active_when=callable` lets the sidebar highlight from outside the tab's own blueprint.

**Sidebar active state — use the page endpoint, not a redirect.** The chassis marks a
tab active when `request.endpoint` matches the entry's `endpoint` (or `active_endpoints`).
If the entry points to a redirect route (e.g. `app.index` → `redirect(url_for("app.page"))`),
the tab will never highlight because the browser lands on `app.page`, not `app.index`.
Always set `endpoint` to the route that actually renders the page. A path-based fallback
exists in the blueprint as a safety net, but correct configuration is the right fix.

---

### `design` — Pill toolbar component (JS)

Floating bottom-center mode/view switcher, served at `/design-static/pill-toolbar.{js,css}`.
Loaded automatically by `base.html` via `{% block pre_scripts %}`.

```js
PillToolbar.create({
    mount: document.getElementById("my-toolbar"),
    items: [
        { value: "table", label: "Table" },
        { value: "time",  label: "Time"  },
        { value: "logic", label: "Logic" },
    ],
    value: "table",          // initial (overridden by persistence)
    onChange: (val) => { /* switch view */ },
    hashKey: "mode",         // persist to URL hash
    // urlParam: "view"      // or: persist to ?view= query string
    // storageKey: "mode"    // or: persist to localStorage
});
```

Initial value priority: `urlParam` → `hashKey` → `storageKey` → `opts.value`.
CSS variables follow the chassis theme automatically.

---

### `settings` — Settings store

```python
from central_server_app_foundation.settings import SettingsStore

store = SettingsStore(db_path="settings.db")   # str or callable () → str
store.init_schema()

store.set_global("key", "value")
store.get_global("key", default="fallback")
store.set_global_json("key", {"a": 1})
store.get_global_json("key", default={})

store.set_user_pref("alice", "theme", "dark")
store.get_user_pref("alice", "theme", default="")
```

Two scopes in one SQLite file: `global_settings` (one value per key, shared) and
`user_preferences` (per-username-key). WAL mode. Schema created idempotently.

---

### `settings_ui` — Settings section registry

```python
from central_server_app_foundation.settings_ui import (
    SettingsShell, SettingsSection, SettingsButton,
    create_settings_blueprint,
)

shell = SettingsShell()
shell.section(SettingsSection(
    id="columns",
    label=_("Column Configuration"),
    icon="columns",
    button=SettingsButton(label=_("Configure"), modal_id="modal-columns"),
))
shell.section(SettingsSection(
    id="db",
    label=_("Database Connection"),
    icon="database",
    button=SettingsButton(label=_("Configure"), modal_id="modal-db"),
    admin_only=True,
))

settings_bp = create_settings_blueprint(
    shell=shell,
    get_role=lambda: session.get("role", "operator"),
    get_is_admin=lambda: session.get("is_admin", False),
)
app.register_blueprint(settings_bp)
```

La sección grid se renderiza vía el partial `_sections.html`. Las apps hacen `{% include %}`
dentro de su propia ruta `/settings` para pasar contexto específico del dominio a los modales.

Role gating: `admin_only` → visible solo para admins. `supervisor_only` → visible para
supervisors y admins. Los admins pasan implícitamente los gates de supervisor.

---

### `wiki` — Wiki store

```python
from central_server_app_foundation.wiki import WikiStore, render_markdown

store = WikiStore(
    db_path="wiki.db",                        # str or callable () → str
    uploads_dir="data/wiki_uploads",          # str or callable () → str
    locale_resolver=get_locale,               # () → "en"|"es"|"de"
    gettext=_,                                # optional
    url_prefix="",                            # for v1.3 reverse-proxy deployments
)
store.init_schema()
store.seed(articles)   # articles is a list of dicts from app's seed module

html = render_markdown(markdown_text)
```

Los artículos tienen campos de título/contenido por locale (`title_en`, `title_es`, `title_de`,
`content_en`, `content_es`, `content_de`). Vuelve al inglés cuando falta contenido en un locale.

Role gating por página vía campo `min_role`. Los uploads de imágenes se aplanan (sin subdirs)
con protección contra path-traversal vía `safe_upload_name`.

`render_markdown` usa: `fenced_code`, `tables`, `toc`, `sane_lists`, `attr_list`, `nl2br`.
No sanitiza HTML (contenido de autor admin es confiable).

---

### `i18n` — Babel wiring

```python
from central_server_app_foundation.i18n import (
    init_babel, make_locale_resolver, DEFAULT_SUPPORTED_LANGUAGES,
)

get_locale = make_locale_resolver(
    supported_languages=("en", "es", "de"),
    default_language="en",
    session_key="lang",
    cookie_key="lang",
)

def create_app():
    app = Flask(__name__)
    init_babel(
        app,
        supported_languages=("en", "es", "de"),
        default_language="en",
        translation_dirs=("translations",),   # app's own translation dir
        locale_selector=get_locale,
    )
```

`init_babel` antepone el directorio `i18n/translations/` de la librería a
`BABEL_TRANSLATION_DIRECTORIES`. Las apps heredan las traducciones del chassis
(~55 strings para auth/settings/wiki UI); los strings sin traducir vuelven al inglés.

`make_locale_resolver` resuelve en orden:
session[session_key] → cookie[cookie_key] → Accept-Language header → default_language.
Seguro de llamar fuera de un request context (retorna default_language).

**Actualizar traducciones del chassis** (tras agregar nuevos strings traducibles a la librería):

```bash
cd central_server_app_foundation/i18n
# Extraer strings del source de la librería
pybabel extract -F babel.cfg -o translations/messages.pot ../..
# Actualizar catálogos existentes
pybabel update -i translations/messages.pot -d translations
# Editar translations/es/LC_MESSAGES/messages.po y de/... manualmente
# Compilar
pybabel compile -d translations
```

---

## Key architectural patterns

### Factory functions everywhere

Every module exports a factory function, not a ready-made object. This means:
- Config is injected, not global — two instances with different DBs coexist cleanly.
- Tests can create isolated instances without shared state.
- Apps stay in control of registration order and blueprint naming.

### Late-binding callables for DB paths

```python
# BAD — path fixed at import time, monkeypatching won't work in tests
store = UserStore(db_path=settings.AUTH_DB_PATH)

# GOOD — path evaluated on every call, test monkeypatch works
store = UserStore(db_path=lambda: settings.AUTH_DB_PATH)
```

All store constructors accept `db_path: str | Callable[[], str]`.

### Template namespace directories

Library templates live under `{module}/templates/central_server_app_foundation/{submodule}/`
so Flask's template loader sees them as `central_server_app_foundation/auth/login.html`.
Apps extend or include them by full namespace path. This prevents collisions with
app-local templates.

### Role hierarchy

```
guest < operator < supervisor < admin
  0         1           2          3
```

`can_publish(role)` → True for supervisor and admin.
Sidebar/SettingsSection gates: `admin_only` checks `is_admin`; `supervisor_only` checks
`role in ("supervisor", "admin")`; admins implicitly pass supervisor gates.

### Callback injection in auth_ui

The auth blueprint accepts optional callables for everything app-specific:
`gettext`, `get_user_pref`, `set_user_pref`, `on_login_hook`. When omitted, sensible
no-op defaults apply. This keeps the library free of any import of the app's services.

### Translation path merging

Library catalog is always prepended; app catalog appended. String resolution:
1. App's own `translations/` (domain strings)
2. Library's `i18n/translations/` (chassis strings: auth/settings/wiki labels)
3. English source text (fallback for untranslated keys)

---

## Testing conventions

```bash
python -m pytest tests/ -q                    # full suite (~279 tests)
python -m pytest tests/test_auth.py -q        # single module
python -m pytest tests/ -k "login" -q         # by keyword
```

### Test isolation patterns

**Store tests** — each test creates a `tmp_path`-based SQLite database:
```python
def test_something(tmp_path):
    store = UserStore(db_path=str(tmp_path / "auth.db"))
    store.init_schema()
    ...
```

**Blueprint tests** — Flask test app + `DictLoader` stubs para el chassis `base.html`:
```python
@pytest.fixture
def test_app(tmp_path, user_store):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "t"
    app.config["TESTING"] = True

    # Stub the chassis base.html so tests don't need the full design blueprint
    from jinja2 import DictLoader, ChoiceLoader
    stub = DictLoader({
        "central_server_app_foundation/design/base.html":
            '{% block content %}{% endblock %}'
            '{% block scripts %}{% endblock %}'
    })
    app.jinja_loader = ChoiceLoader([stub, app.jinja_loader])

    auth_bp = create_auth_blueprint(user_store=user_store, ...)
    app.register_blueprint(auth_bp)
    return app
```

**Evitar assertions de flash-content** — el stub base.html no renderiza flash messages,
por lo que los tests comprueban estado (contenido del store, redirect target, status code)
en vez del cuerpo de la respuesta.

**Late-binding monkeypatching**:
```python
def test_db_path_callable(tmp_path, monkeypatch):
    alt = str(tmp_path / "alt.db")
    monkeypatch.setattr("app.services.auth_service._store._db_path", lambda: alt)
    ...
```

### Pre-existing baseline failures

Al correr la suite de tests de la **consumer app** (conter-stats), hay un pequeño número
de fallos preexistentes sin relación con el chassis. Son conocidos y estables — no deben
aparecer en la suite propia de la librería chassis.

---

## Dependency and install notes

La librería tiene dependencias duras mínimas e intencionales:
```
flask>=3.0
werkzeug>=3.0
flask-babel>=4.0
```

`markdown` (para wiki rendering) NO está listado — se usa internamente pero los
consumers típicamente ya lo tienen. Si se agrega una nueva dependencia dura, debe ser
algo que todos los consumers siempre querrán.

Las dependencias pesadas opcionales (ej. `mysql-connector-python`) nunca deben
agregarse — el chassis no tiene por qué tocar fuentes de datos específicas de cada app.

### Installing in consumer apps

```bash
pip install "central-server-app-foundation @ git+https://github.com/fsebastianrebollar/central_server_app_foundation.git"
```

Hasta que la librería publique tags, `pip install --upgrade` siempre instala desde `HEAD`
del branch por defecto.

---

## Supervisor contract v1.3 (context for contract module)

The `contract` module implements the Conter Central Server supervision protocol:

| Endpoint | Shape |
|---|---|
| `GET /health` | `{status, version, uptime_seconds, db: "ok"\|"error"}` |
| `GET /version` | `{app, version, built, contract, display_name, description}` |
| `GET /icon` | PNG file (404 if absent) |
| `POST /shutdown` | `{"ok": true}` then `os._exit(0)` after 200 ms |

CLI flags requeridos por v1.3:
`--headless`, `--host`, `--port`, `--log-level`, `--data-dir`, `--shutdown-token`,
`--prefix`, `--info`, `--version`.

`--prefix PATH` habilita despliegue reverse-proxy: configura `ProxyFix`, establece
`APPLICATION_ROOT`, limita el alcance de la session cookie. Las apps NO deben re-implementar esto.

`--info` imprime `{app, display_name, description, contract, version}` a stdout y
sale con código 0 **sin arrancar Flask** — el servidor central lo invoca durante
la carga del servicio para leer metadatos del binario.

---

## Non-goals

- No PyPI publishing (todavía). Instalar vía `git+https://`.
- No CSS framework — vanilla CSS + CSS custom properties para theming.
- No JS framework — vanilla JS únicamente.
- No database connection pooling ni ORM — solo SQLite; los servicios de cada app manejan
  sus propias conexiones MariaDB/Postgres.
- No server-side session store — se asume la session de cookie firmada de Flask.
- No websockets, background tasks ni caching — esos quedan en cada app.

---

## What to work on next (known future work)

- Publicar un git tag para installs versionados (`v0.1.0`) para que los consumers puedan
  bloquear a un release específico en vez de siempre rastrear `HEAD`.
- `markdown` debe agregarse como dependencia explícita en `pyproject.toml`.
- Agregar un `CHANGELOG.md` apropiado.
- Considerar agregar una sección `pytest.ini` o `[tool.pytest.ini_options]` a
  `pyproject.toml` para que `pytest` funcione desde la raíz del repo sin flags extra.
- Mayor adopción del chassis en `ini-configurator` (actualmente solo usa `i18n`).
  Candidatos: `auth`, `contract.health`, `contract.cli`.
