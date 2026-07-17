"""Tests for `central_server_app_contract.sso` — token + integrations.

Token: roundtrip, tamper rejection, expiry, wrong secret.
Central: cookie issued at login, refreshed when stale, deleted at
logout, session hydrated back from a valid cookie, /sso/logout.
Gate: session hydration, redirect to central login with next, login /
logout endpoint interception, public endpoints pass-through, sliding
refresh.
"""
from __future__ import annotations

import time

import pytest
from flask import Flask, session

from central_server_app_contract.sso import (
    SSO_COOKIE_NAME,
    install_sso_central,
    install_sso_gate,
    issue_token,
    validate_token,
)

SECRET = "test-sso-secret"


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------

def test_token_roundtrip():
    token = issue_token(SECRET, username="paco", role="supervisor", is_admin=False)
    identity = validate_token(SECRET, token, max_age_seconds=60)
    assert identity["username"] == "paco"
    assert identity["role"] == "supervisor"
    assert identity["is_admin"] is False
    assert identity["age_seconds"] < 5


def test_token_rejects_tampering():
    token = issue_token(SECRET, username="paco", role="operator", is_admin=False)
    assert validate_token(SECRET, token[:-2] + "xx", max_age_seconds=60) is None


def test_token_rejects_wrong_secret():
    token = issue_token(SECRET, username="paco", role="admin", is_admin=True)
    assert validate_token("other-secret", token, max_age_seconds=60) is None


def test_token_rejects_expired():
    token = issue_token(SECRET, username="paco", role="admin", is_admin=True)
    # itsdangerous timestamps have 1 s granularity — sleep past 2 s so
    # the computed age strictly exceeds max_age=1.
    time.sleep(2.2)
    assert validate_token(SECRET, token, max_age_seconds=1) is None


def test_token_rejects_empty():
    assert validate_token(SECRET, "", max_age_seconds=60) is None
    assert validate_token("", "anything", max_age_seconds=60) is None


# ---------------------------------------------------------------------------
# Central integration
# ---------------------------------------------------------------------------

@pytest.fixture()
def central_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "t"
    app.config["TESTING"] = True

    install_sso_central(
        app, secret=SECRET, max_age_seconds=1800, login_endpoint="login"
    )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        session["user_id"] = "paco"
        session["role"] = "admin"
        session["is_admin"] = True
        return "ok"

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return "bye"

    @app.route("/whoami")
    def whoami():
        return session.get("user_id", "")

    return app


def _extract_sso_cookie(response) -> str | None:
    for header in response.headers.getlist("Set-Cookie"):
        if header.startswith(f"{SSO_COOKIE_NAME}="):
            value = header.split(";")[0].split("=", 1)[1]
            return value or None
    return None


def test_central_issues_cookie_on_login(central_app):
    client = central_app.test_client()
    resp = client.post("/login")
    token = _extract_sso_cookie(resp)
    assert token
    identity = validate_token(SECRET, token, max_age_seconds=60)
    assert identity["username"] == "paco"
    assert identity["is_admin"] is True


def test_central_deletes_cookie_on_logout(central_app):
    client = central_app.test_client()
    client.post("/login")
    resp = client.post("/logout")
    # Deleted cookie → Set-Cookie with empty value + immediate expiry.
    headers = [
        h for h in resp.headers.getlist("Set-Cookie")
        if h.startswith(f"{SSO_COOKIE_NAME}=")
    ]
    assert headers and 'Max-Age=0' in headers[0]


def test_central_hydrates_session_from_cookie(central_app):
    client = central_app.test_client()
    token = issue_token(SECRET, username="ana", role="operator", is_admin=False)
    client.set_cookie(SSO_COOKIE_NAME, token)
    resp = client.get("/whoami")
    assert resp.data == b"ana"


def test_central_no_cookie_for_anonymous(central_app):
    client = central_app.test_client()
    resp = client.get("/whoami")
    assert _extract_sso_cookie(resp) is None


def test_central_fresh_cookie_not_reissued(central_app):
    client = central_app.test_client()
    client.post("/login")
    resp = client.get("/whoami")
    # Cookie is seconds old — no refresh expected on this response.
    assert _extract_sso_cookie(resp) is None


def test_central_sso_logout_route(central_app):
    client = central_app.test_client()
    client.post("/login")
    resp = client.get("/sso/logout")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
    headers = [
        h for h in resp.headers.getlist("Set-Cookie")
        if h.startswith(f"{SSO_COOKIE_NAME}=")
    ]
    assert headers and "Max-Age=0" in headers[0]


# ---------------------------------------------------------------------------
# Subapp gate
# ---------------------------------------------------------------------------

@pytest.fixture()
def gate_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "t"
    app.config["TESTING"] = True

    install_sso_gate(
        app,
        secret=SECRET,
        central_url="http://127.0.0.1:5000",
        max_age_seconds=1800,
        public_endpoints={"health"},
        login_endpoints=("login", "login_guest"),
        logout_endpoint="logout",
    )

    @app.route("/login")
    def login():
        return "local login form"

    @app.route("/login/guest")
    def login_guest():
        return "guest"

    @app.route("/logout", methods=["POST", "GET"])
    def logout():
        session.clear()
        return "local logout"

    @app.route("/health")
    def health():
        return "healthy"

    @app.route("/data")
    def data():
        return session.get("user_id", "") + ":" + session.get("role", "")

    return app


def _token(username="paco", role="supervisor", is_admin=False):
    return issue_token(SECRET, username=username, role=role, is_admin=is_admin)


def test_gate_redirects_anonymous_to_central_login(gate_app):
    client = gate_app.test_client()
    resp = client.get("/data", base_url="http://plant-server:5001")
    assert resp.status_code == 302
    location = resp.headers["Location"]
    # Same hostname the browser used, Central's port, next back to us.
    assert location.startswith("http://plant-server:5000/login?next=")
    assert "plant-server%3A5001%2Fdata" in location


def test_gate_hydrates_session_from_cookie(gate_app):
    client = gate_app.test_client()
    client.set_cookie(SSO_COOKIE_NAME, _token())
    resp = client.get("/data")
    assert resp.data == b"paco:supervisor"


def test_gate_public_endpoint_needs_no_token(gate_app):
    client = gate_app.test_client()
    assert client.get("/health").status_code == 200


def test_gate_intercepts_local_login(gate_app):
    client = gate_app.test_client()
    resp = client.get("/login", base_url="http://plant-server:5001")
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("http://plant-server:5000/login")


def test_gate_login_passes_through_when_authenticated(gate_app):
    client = gate_app.test_client()
    client.set_cookie(SSO_COOKIE_NAME, _token())
    resp = client.get("/login")
    # The app's own login route runs (and would bounce to its landing).
    assert resp.status_code == 200
    assert resp.data == b"local login form"


def test_gate_intercepts_logout_to_central(gate_app):
    client = gate_app.test_client()
    client.set_cookie(SSO_COOKIE_NAME, _token())
    resp = client.post("/logout", base_url="http://plant-server:5001")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "http://plant-server:5000/sso/logout"


def test_gate_expired_token_redirects(gate_app):
    client = gate_app.test_client()
    client.set_cookie(SSO_COOKIE_NAME, _token())
    # 1 s timestamp granularity — sleep past 2 s so age > max_age=1.
    time.sleep(2.2)
    gate_app.before_request_funcs = {}
    gate_app.after_request_funcs = {}
    install_sso_gate(
        gate_app,
        secret=SECRET,
        central_url="http://127.0.0.1:5000",
        max_age_seconds=1,
        public_endpoints={"health"},
        login_endpoints=("login", "login_guest"),
        logout_endpoint="logout",
    )
    resp = client.get("/data")
    assert resp.status_code == 302


def test_gate_stale_token_is_refreshed(gate_app):
    """A token older than refresh_after_seconds gets re-issued."""
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "t"
    app.config["TESTING"] = True
    install_sso_gate(
        app,
        secret=SECRET,
        central_url="http://127.0.0.1:5000",
        max_age_seconds=1800,
        refresh_after_seconds=1,
    )

    @app.route("/data")
    def data():
        return "ok"

    client = app.test_client()
    client.set_cookie(SSO_COOKIE_NAME, _token())
    time.sleep(1.2)
    resp = client.get("/data")
    assert _extract_sso_cookie(resp) is not None


def test_gate_guest_login_redirects_to_central(gate_app):
    client = gate_app.test_client()
    resp = client.get("/login/guest", base_url="http://plant-server:5001")
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("http://plant-server:5000/login")
