"""Authentication chassis — SQLite user store + role helpers.

Every Conter app authenticates the same way: local SQLite `users`
table, werkzeug password hashing, three roles (`operator`,
`supervisor`, `admin`), one bootstrap admin created on first boot.
This package ships that logic as a class so each app only has to
decide where the DB lives and which bootstrap admin to seed.

The canonical usage (see `app/services/auth_service.py` in
conter-stats for a working example):

    from central_server_app_foundation.auth import UserStore, can_publish, VALID_ROLES

    _store = UserStore(
        db_path=lambda: _DB_PATH,              # late binding for tests
        admin_user=os.environ.get("TEMPLATE_ADMIN_USER", "admin"),
        admin_pass=os.environ.get("TEMPLATE_ADMIN_PASS", "changeme"),
        gettext=flask_babel.gettext,           # optional, identity default
    )

    init_auth_db = _store.init_schema
    authenticate = _store.authenticate
    create_user  = _store.create_user
    ...

Apps that don't use Babel can omit `gettext` — error messages fall
back to plain English, which is still fine for logs/API responses.
"""
from central_server_app_foundation.auth.user_store import (
    VALID_ROLES,
    UserStore,
    can_publish,
)
from central_server_app_foundation.auth.remote_store import RemoteUserStore
from central_server_app_foundation.auth.factory import make_user_store

__all__ = [
    "UserStore",
    "RemoteUserStore",
    "make_user_store",
    "VALID_ROLES",
    "can_publish",
]
