"""Remote user store — same interface as `UserStore`, backed by the
Central's auth API instead of a local SQLite file.

Drop-in duck type: `create_auth_blueprint(user_store=...)` and every
`auth_service.py` call site work unchanged. Write operations that
would fork the user base (create/delete/set_role) raise ValueError —
in central mode users are managed exclusively from the Central's
panel.

Transport is urllib (stdlib) so the foundation gains no dependency.
TLS verification is off by default because the Central ships a
self-signed certificate and every call is loopback or plant-LAN;
pass `verify_tls=True` when a real certificate is in place.
"""
from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.request
from typing import Callable

from central_server_app_contract.auth.roles import VALID_ROLES, _default_gettext

logger = logging.getLogger(__name__)

API_PREFIX = "/api/auth/v1"


class RemoteUserStore:
    """Credential operations proxied to the Central's auth API."""

    is_remote = True

    def __init__(
        self,
        *,
        base_url: str,
        service_key: str,
        timeout: float = 4.0,
        verify_tls: bool = False,
        valid_roles: tuple[str, ...] = VALID_ROLES,
        gettext: Callable[..., str] = _default_gettext,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_key = service_key
        self._timeout = timeout
        self._valid_roles = tuple(valid_roles)
        self._ = gettext
        if verify_tls:
            self._ssl_context = ssl.create_default_context()
        else:
            self._ssl_context = ssl._create_unverified_context()  # noqa: S323

    @property
    def valid_roles(self) -> tuple[str, ...]:
        return self._valid_roles

    # ---- transport --------------------------------------------------------

    def _request(self, method: str, path: str, payload: dict | None = None):
        """Return (status, parsed_json). Raises ConnectionError on I/O failure."""
        url = f"{self._base_url}{API_PREFIX}{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._service_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(
                req, timeout=self._timeout, context=self._ssl_context
            ) as resp:
                return resp.status, json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode() or "{}")
            except (ValueError, UnicodeDecodeError):
                body = {}
            return e.code, body
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ConnectionError(
                f"Central auth API unreachable at {self._base_url}: {e}"
            ) from e

    # ---- schema (no-op) ---------------------------------------------------

    def init_schema(self) -> None:
        """Nothing to initialise — the user table lives on the Central."""

    # ---- credential checks ------------------------------------------------

    def authenticate(self, username: str, password: str) -> dict | None:
        """Verify credentials against the Central. Returns user dict or None.

        An unreachable Central is reported as a failed login (None) —
        the caller's UX for both cases is the same login-rejected path,
        and the incident is logged for the operator.
        """
        try:
            status, body = self._request(
                "POST", "/verify", {"username": username, "password": password}
            )
        except ConnectionError as e:
            logger.warning("SSO verify failed, Central unreachable: %s", e)
            return None
        if status == 200 and body.get("ok"):
            return {
                "username": body.get("username", username),
                "is_admin": bool(body.get("is_admin")),
                "role": body.get("role", "operator"),
            }
        return None

    # ---- user CRUD --------------------------------------------------------

    def _managed_centrally(self) -> ValueError:
        return ValueError(self._("Users are managed by Conter Central."))

    def create_user(self, username: str, password: str) -> None:
        raise self._managed_centrally()

    def delete_user(self, username: str) -> None:
        raise self._managed_centrally()

    def set_role(self, username: str, role: str) -> None:
        raise self._managed_centrally()

    def change_password(self, username: str, new_password: str) -> None:
        """Self-service password change, forwarded to the Central.

        The auth blueprint verifies the current password (via
        `authenticate`) before calling this, mirroring the local flow.
        """
        try:
            status, body = self._request(
                "POST",
                "/change-password",
                {"username": username, "new_password": new_password},
            )
        except ConnectionError:
            raise ValueError(
                self._("Conter Central is unreachable — try again later.")
            ) from None
        if status != 200:
            raise ValueError(body.get("error") or self._("Password change failed."))

    # ---- lookups ----------------------------------------------------------

    def list_users(self) -> list[dict]:
        try:
            status, body = self._request("GET", "/users")
        except ConnectionError as e:
            logger.warning("SSO user listing failed, Central unreachable: %s", e)
            return []
        if status == 200:
            return body.get("users", [])
        return []

    def get_role(self, username: str) -> str:
        for user in self.list_users():
            if user.get("username") == username:
                return user.get("role", "operator")
        return "operator"
