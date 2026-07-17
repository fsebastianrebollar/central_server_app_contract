"""Role taxonomy + identity translator — the auth vocabulary of CONTER.

Extracted from the old local ``UserStore`` when the chassis was reduced
to the supervisor contract: the role names travel over the wire (the
Central's ``/api/auth/v1`` responses, the SSO cookie payload), so they
are contract, while the SQLite store that used to define them is
chassis and now lives in ``control_foundation``.
"""
from __future__ import annotations

VALID_ROLES = ("operator", "supervisor", "admin")


def can_publish(role: str) -> bool:
    """Supervisors and admins can publish public workspaces.

    Stateless helper — lives here because the role taxonomy does.
    """
    return role in ("supervisor", "admin")


def _default_gettext(string: str, **variables) -> str:
    """Identity translator — returns the raw string after %-formatting.

    Matches ``flask_babel.gettext``'s signature so apps with Babel can
    drop it in without a wrapper: ``gettext=flask_babel.gettext``.
    """
    return string % variables if variables else string
