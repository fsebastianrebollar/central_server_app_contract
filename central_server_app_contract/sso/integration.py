"""Flask integration for the SSO cookie — Central issuer + subapp gate.

Both installers hook `before_request` / `after_request` on the app.
They must be called inside `create_app()` BEFORE the app registers its
own `require_login`-style gate, so identity hydration runs first
(Flask executes app-level before_request hooks in registration order).
"""
from __future__ import annotations

from typing import Callable, Iterable
from urllib.parse import urlencode, urlsplit

from flask import g, redirect, request, session

from central_server_app_contract.sso.token import (
    SSO_COOKIE_NAME,
    issue_token,
    validate_token,
)

# Session keys owned by the SSO layer. `is_guest` is forced False on
# hydration — guest sessions are app-local and never carried by SSO.
_IDENTITY_KEYS = ("user_id", "role", "is_admin", "is_guest")


def _as_getter(value: int | Callable[[], int]) -> Callable[[], int]:
    if callable(value):
        return value
    return lambda: value


def _read_token(secret: str, max_age: int) -> dict | None:
    return validate_token(
        secret, request.cookies.get(SSO_COOKIE_NAME, ""), max_age_seconds=max_age
    )


def _sync_session(identity: dict) -> None:
    """Mirror the token identity into the session (only when it differs)."""
    if (
        session.get("user_id") != identity["username"]
        or session.get("role") != identity["role"]
        or bool(session.get("is_admin")) != identity["is_admin"]
        or session.get("is_guest")
    ):
        session["user_id"] = identity["username"]
        session["role"] = identity["role"]
        session["is_admin"] = identity["is_admin"]
        session["is_guest"] = False


def _clear_identity() -> None:
    for key in _IDENTITY_KEYS:
        session.pop(key, None)


def _set_cookie(response, secret: str, max_age: int) -> None:
    token = issue_token(
        secret,
        username=session["user_id"],
        role=session.get("role", "operator"),
        is_admin=bool(session.get("is_admin")),
    )
    response.set_cookie(
        SSO_COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        samesite="Lax",
        path="/",
    )


def _is_public(endpoint: str | None, public_endpoints: frozenset[str]) -> bool:
    if endpoint is None:
        return True  # 404s and the like — nothing to protect
    if endpoint in public_endpoints:
        return True
    return endpoint == "static" or endpoint.endswith(".static")


# ---------------------------------------------------------------------------
# Central — session is the source of truth, cookie mirrors it.
# ---------------------------------------------------------------------------

def install_sso_central(
    app,
    *,
    secret: str,
    max_age_seconds: int | Callable[[], int],
    refresh_after_seconds: int = 60,
    login_endpoint: str = "auth.login",
) -> None:
    """Wire the Central as the SSO issuer.

    - Login (any route that puts `user_id` in the session) → cookie
      issued on the response.
    - Activity → cookie re-signed once it is older than
      `refresh_after_seconds` (sliding expiry).
    - Logout (session cleared while a valid cookie is present) →
      cookie deleted, which logs the user out of every app at once.
    - A valid cookie with an expired Flask session hydrates the
      session back, so working inside a subapp keeps the Central
      session alive too.

    Also registers `GET /sso/logout` — the single logout endpoint the
    subapps redirect to.
    """
    get_max_age = _as_getter(max_age_seconds)

    @app.before_request
    def _sso_central_sync():
        identity = _read_token(secret, get_max_age())
        g._sso_identity = identity
        if identity and not session.get("user_id"):
            _sync_session(identity)
        return None

    @app.after_request
    def _sso_central_cookie(response):
        identity = getattr(g, "_sso_identity", None)
        if session.get("user_id") and not session.get("is_guest"):
            stale = identity is None or identity["age_seconds"] > refresh_after_seconds
            if stale or identity["username"] != session["user_id"]:
                _set_cookie(response, secret, get_max_age())
        elif identity is not None:
            # Valid cookie but no logged-in session → logout just
            # happened. Drop the cookie so every app logs out.
            response.delete_cookie(SSO_COOKIE_NAME, path="/")
        return response

    def _sso_logout():
        from flask import url_for

        session.clear()
        response = redirect(url_for(login_endpoint))
        response.delete_cookie(SSO_COOKIE_NAME, path="/")
        return response

    app.add_url_rule("/sso/logout", "sso.logout", _sso_logout, methods=["GET"])


# ---------------------------------------------------------------------------
# Subapp — cookie is the source of truth, session mirrors it.
# ---------------------------------------------------------------------------

def install_sso_gate(
    app,
    *,
    secret: str,
    central_url: str,
    max_age_seconds: int | Callable[[], int],
    public_endpoints: Iterable[str] = (),
    refresh_after_seconds: int = 60,
    login_endpoints: Iterable[str] = ("auth.login", "auth.login_guest"),
    logout_endpoint: str = "auth.logout",
) -> None:
    """Wire a managed subapp as an SSO consumer.

    `central_url` is the server-to-server base URL the supervisor
    passed via `--auth-url` (e.g. `http://127.0.0.1:5000`). Browser
    redirects reuse its scheme and port but swap in the hostname the
    browser actually used, so the same build works on localhost, a
    LAN IP or a DNS name.
    """
    get_max_age = _as_getter(max_age_seconds)
    public = frozenset(public_endpoints)
    login_eps = frozenset(login_endpoints)
    central = urlsplit(central_url)

    def _central_base() -> str:
        # Behind the Central's reverse proxy the forwarded host/proto
        # ARE the Central's browser-facing origin — use them directly.
        fwd_host = request.headers.get("X-Forwarded-Host")
        if fwd_host:
            proto = request.headers.get("X-Forwarded-Proto", "http")
            return f"{proto}://{fwd_host}"
        # Direct access: same hostname the browser used, the Central's
        # scheme and port from --auth-url.
        host = request.host.split(":")[0]
        port = f":{central.port}" if central.port else ""
        return f"{central.scheme}://{host}{port}"

    def _central_login_redirect(next_url: str):
        query = urlencode({"next": next_url})
        return redirect(f"{_central_base()}/login?{query}")

    @app.before_request
    def _sso_gate():
        identity = _read_token(secret, get_max_age())
        g._sso_identity = identity

        endpoint = request.endpoint

        if endpoint == logout_endpoint:
            # Logout is global: clear the local mirror and hand over
            # to the Central, which deletes the SSO cookie.
            session.clear()
            return redirect(f"{_central_base()}/sso/logout")

        if identity is not None:
            _sync_session(identity)
            if endpoint in login_eps:
                # Already signed in — let the app's own login route
                # bounce to its landing page (it sees session.user_id).
                return None
            return None

        # No valid token from here on.
        _clear_identity()
        if endpoint in login_eps:
            # The app's own login page never renders in SSO mode —
            # credentials are only ever typed into the Central.
            return _central_login_redirect(request.url_root)
        if _is_public(endpoint, public):
            return None
        return _central_login_redirect(request.url)

    @app.after_request
    def _sso_refresh(response):
        identity = getattr(g, "_sso_identity", None)
        if identity is not None and identity["age_seconds"] > refresh_after_seconds:
            # Keep the sliding window moving while the user works in
            # this app. Cookies are host-scoped (ports ignored), so
            # this refresh is visible to the Central and siblings.
            _set_cookie(response, secret, get_max_age())
        return response
