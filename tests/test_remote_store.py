"""Tests for `RemoteUserStore` against a fake Central auth API.

Spins a real threaded HTTP server so the urllib transport, bearer
header, JSON bodies and error paths are exercised end to end.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from central_server_app_contract.auth import (
    RemoteUserStore,
    remote_user_store_from_env,
)

SERVICE_KEY = "svc-key-123"


class _FakeCentral(BaseHTTPRequestHandler):
    users = [
        {"username": "conter", "role": "admin", "is_admin": True},
        {"username": "ana", "role": "operator", "is_admin": False},
    ]

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {SERVICE_KEY}"

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        if not self._authorized():
            return self._send(401, {"error": "bad key"})
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/auth/v1/verify":
            if data.get("username") == "ana" and data.get("password") == "s3cret":
                return self._send(
                    200,
                    {"ok": True, "username": "ana", "role": "operator",
                     "is_admin": False},
                )
            return self._send(401, {"error": "invalid credentials"})
        if self.path == "/api/auth/v1/change-password":
            if data.get("username") == "ghost":
                return self._send(404, {"error": "no such user"})
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})

    def do_GET(self):  # noqa: N802
        if not self._authorized():
            return self._send(401, {"error": "bad key"})
        if self.path == "/api/auth/v1/users":
            return self._send(200, {"users": self.users})
        return self._send(404, {"error": "not found"})

    def log_message(self, *args):  # silence test output
        pass


@pytest.fixture(scope="module")
def fake_central():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeCentral)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture()
def store(fake_central):
    return RemoteUserStore(base_url=fake_central, service_key=SERVICE_KEY)


def test_authenticate_ok(store):
    user = store.authenticate("ana", "s3cret")
    assert user == {"username": "ana", "is_admin": False, "role": "operator"}


def test_authenticate_bad_password(store):
    assert store.authenticate("ana", "wrong") is None


def test_authenticate_bad_service_key(fake_central):
    bad = RemoteUserStore(base_url=fake_central, service_key="nope")
    assert bad.authenticate("ana", "s3cret") is None


def test_authenticate_central_down_returns_none():
    dead = RemoteUserStore(
        base_url="http://127.0.0.1:1", service_key=SERVICE_KEY, timeout=0.3
    )
    assert dead.authenticate("ana", "s3cret") is None


def test_list_users(store):
    users = store.list_users()
    assert [u["username"] for u in users] == ["conter", "ana"]


def test_get_role(store):
    assert store.get_role("conter") == "admin"
    assert store.get_role("unknown") == "operator"


def test_change_password_ok(store):
    store.change_password("ana", "newpass")  # no raise


def test_change_password_error_raises(store):
    with pytest.raises(ValueError, match="no such user"):
        store.change_password("ghost", "x")


def test_change_password_central_down_raises():
    dead = RemoteUserStore(
        base_url="http://127.0.0.1:1", service_key=SERVICE_KEY, timeout=0.3
    )
    with pytest.raises(ValueError, match="unreachable"):
        dead.change_password("ana", "x")


def test_crud_refused(store):
    with pytest.raises(ValueError):
        store.create_user("x", "y")
    with pytest.raises(ValueError):
        store.delete_user("x")
    with pytest.raises(ValueError):
        store.set_role("x", "admin")


def test_init_schema_is_noop(store):
    store.init_schema()  # must not raise nor call the network


def test_is_remote_flag():
    assert RemoteUserStore.is_remote is True


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def test_factory_none_outside_central_mode(monkeypatch):
    monkeypatch.delenv("CONTER_AUTH_URL", raising=False)
    monkeypatch.delenv("CONTER_AUTH_KEY", raising=False)
    assert remote_user_store_from_env() is None


def test_factory_remote_from_env(monkeypatch):
    monkeypatch.setenv("CONTER_AUTH_URL", "http://127.0.0.1:5000")
    monkeypatch.setenv("CONTER_AUTH_KEY", "k")
    store = remote_user_store_from_env()
    assert isinstance(store, RemoteUserStore)


def test_factory_explicit_args_beat_env(monkeypatch):
    monkeypatch.delenv("CONTER_AUTH_URL", raising=False)
    store = remote_user_store_from_env(
        auth_url="https://central:5000", auth_key="k"
    )
    assert isinstance(store, RemoteUserStore)
