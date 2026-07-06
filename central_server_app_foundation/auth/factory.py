"""Store factory — local SQLite or remote Central, decided by env.

Apps call `make_user_store(...)` with the exact arguments they used
to pass to `UserStore`. When the supervisor launched the app with
`--auth-url` / `--auth-key` (contract v1.4, propagated as
`CONTER_AUTH_URL` / `CONTER_AUTH_KEY`), a `RemoteUserStore` is
returned instead and the local arguments are simply ignored. Without
those env vars the behaviour is byte-for-byte the pre-v1.4 one.
"""
from __future__ import annotations

import os
from typing import Callable

from central_server_app_foundation.auth.remote_store import RemoteUserStore
from central_server_app_foundation.auth.user_store import (
    VALID_ROLES,
    UserStore,
    _default_gettext,
)


def make_user_store(
    *,
    db_path: str | Callable[[], str],
    admin_user: str,
    admin_pass: str,
    valid_roles: tuple[str, ...] = VALID_ROLES,
    gettext: Callable[..., str] = _default_gettext,
    auth_url: str | None = None,
    auth_key: str | None = None,
) -> UserStore | RemoteUserStore:
    """Return the right store for the current launch mode."""
    auth_url = auth_url or os.environ.get("CONTER_AUTH_URL", "")
    auth_key = auth_key if auth_key is not None else os.environ.get("CONTER_AUTH_KEY", "")
    if auth_url:
        return RemoteUserStore(
            base_url=auth_url,
            service_key=auth_key,
            valid_roles=valid_roles,
            gettext=gettext,
        )
    return UserStore(
        db_path=db_path,
        admin_user=admin_user,
        admin_pass=admin_pass,
        valid_roles=valid_roles,
        gettext=gettext,
    )
