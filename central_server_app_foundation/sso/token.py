"""SSO token — a signed, timestamped identity payload.

Uses itsdangerous (already a Flask dependency) with a fixed salt so
the Central and every subapp derive the same signing key from the
shared secret. The payload is deliberately minimal: identity only,
no per-app claims — apps resolve permissions from the role.
"""
from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SSO_COOKIE_NAME = "conter_sso"

_SALT = "conter-sso-v1"


def _serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt=_SALT)


def issue_token(secret: str, *, username: str, role: str, is_admin: bool) -> str:
    """Sign an identity payload. The timestamp is added by itsdangerous."""
    return _serializer(secret).dumps(
        {"u": username, "r": role, "a": bool(is_admin)}
    )


def validate_token(secret: str, token: str, *, max_age_seconds: int) -> dict | None:
    """Verify signature + freshness. Returns identity dict or None.

    The returned dict carries `age_seconds` so callers can decide
    whether to re-issue the cookie (sliding expiry) without a second
    parse.
    """
    if not token or not secret:
        return None
    ser = _serializer(secret)
    try:
        payload, timestamp = ser.loads(
            token, max_age=max_age_seconds, return_timestamp=True
        )
    except (SignatureExpired, BadSignature):
        return None
    if not isinstance(payload, dict) or "u" not in payload:
        return None
    from datetime import datetime, timezone

    age = (datetime.now(timezone.utc) - timestamp).total_seconds()
    return {
        "username": payload["u"],
        "role": payload.get("r", "operator"),
        "is_admin": bool(payload.get("a")),
        "age_seconds": max(0.0, age),
    }
