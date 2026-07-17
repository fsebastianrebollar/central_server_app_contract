"""Remote auth — the credential side of the CONTER contract (v1.4).

This package no longer ships a local user store: that chassis moved to
``control_foundation`` (``control_foundation.ui.auth.UserStore``). What
remains is what only makes sense against the Central:

- ``RemoteUserStore`` — duck type of a local store, backed by the
  Central's ``/api/auth/v1`` API (bearer service key, urllib, stdlib).
- ``remote_user_store_from_env`` — returns it when the supervisor
  launched the app in central mode (``CONTER_AUTH_URL`` /
  ``CONTER_AUTH_KEY``), or ``None`` outside it.
- ``VALID_ROLES`` / ``can_publish`` — the role taxonomy that travels
  over the wire (API responses, SSO cookie payload).

Canonical wiring in a ``control_foundation`` app:

    from central_server_app_contract.auth import remote_user_store_from_env

    create_control_app(..., user_store=remote_user_store_from_env())
"""
from central_server_app_contract.auth.factory import remote_user_store_from_env
from central_server_app_contract.auth.remote_store import RemoteUserStore
from central_server_app_contract.auth.roles import VALID_ROLES, can_publish

__all__ = [
    "RemoteUserStore",
    "remote_user_store_from_env",
    "VALID_ROLES",
    "can_publish",
]
