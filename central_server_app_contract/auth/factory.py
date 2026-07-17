"""Remote store factory — builds a ``RemoteUserStore`` from the contract env.

When the supervisor launches an app in central mode (contract v1.4,
``--auth-url`` / ``--auth-key`` propagated as ``CONTER_AUTH_URL`` /
``CONTER_AUTH_KEY``), this returns the remote store; otherwise it
returns ``None`` and the caller keeps whatever local store its chassis
provides. Apps on ``control_foundation`` wire it in one line:

    create_control_app(..., user_store=remote_user_store_from_env())

``user_store=None`` there means "build the local SQLite store", so the
same line covers both launch modes.
"""
from __future__ import annotations

import os
from typing import Callable

from central_server_app_contract.auth.remote_store import RemoteUserStore
from central_server_app_contract.auth.roles import VALID_ROLES, _default_gettext


def remote_user_store_from_env(
    *,
    valid_roles: tuple[str, ...] = VALID_ROLES,
    gettext: Callable[..., str] = _default_gettext,
    auth_url: str | None = None,
    auth_key: str | None = None,
) -> RemoteUserStore | None:
    """Return the remote store for central mode, or ``None`` outside it.

    Explicit ``auth_url`` / ``auth_key`` beat the env vars — useful in
    tests and in apps that resolve the launch flags themselves.
    """
    auth_url = auth_url or os.environ.get("CONTER_AUTH_URL", "")
    auth_key = auth_key if auth_key is not None else os.environ.get(
        "CONTER_AUTH_KEY", "")
    if not auth_url:
        return None
    return RemoteUserStore(
        base_url=auth_url,
        service_key=auth_key,
        valid_roles=valid_roles,
        gettext=gettext,
    )
