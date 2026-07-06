"""Single sign-on chassis — signed-cookie SSO across Conter apps.

The Central issues a signed `conter_sso` cookie at login. Because
browsers scope cookies by hostname (ignoring the port), every app
served from the same host — directly on its own port or through the
Central's reverse proxy — receives the cookie and can validate it
locally with the shared signing secret. No per-request round trip to
the Central is needed.

Two integration points:

- `install_sso_central(app, ...)` — for the Central itself. Keeps the
  cookie in sync with the Flask session: issues/refreshes it while a
  user is logged in, deletes it on logout, and hydrates an expired
  Flask session from a still-valid cookie.
- `install_sso_gate(app, ...)` — for managed subapps. The cookie is
  the source of truth: a valid token hydrates the local session, an
  invalid/missing one redirects the browser to the Central's login
  page. The app's own /login, /login/guest and /logout endpoints are
  intercepted so the Central stays the single place where credentials
  are entered and cleared.

Token payloads carry `{username, role, is_admin}` plus the signing
timestamp; expiry is enforced at validation time against the session
lifetime, and any app refreshes the cookie while the user is active
(sliding expiry).
"""
from central_server_app_foundation.sso.token import (
    SSO_COOKIE_NAME,
    issue_token,
    validate_token,
)
from central_server_app_foundation.sso.integration import (
    install_sso_central,
    install_sso_gate,
)

__all__ = [
    "SSO_COOKIE_NAME",
    "issue_token",
    "validate_token",
    "install_sso_central",
    "install_sso_gate",
]
