"""Unit tests for `create_health_blueprint` — the library-level factory.

These tests instantiate a minimal Flask app that registers ONLY the
blueprint under test. Keeping them in the package ensures the contract
can be validated without standing up the whole conter-stats suite.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from flask import Flask

from central_server_app_contract.contract import create_health_blueprint


def _make_app(tmp_path: Path, *, icon_exists: bool = True,
              db_probe_return: str = "ok") -> Flask:
    icon = tmp_path / "icon.png"
    if icon_exists:
        # 8-byte PNG signature is enough for send_file's mime detection.
        icon.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

    bp = create_health_blueprint(
        app_name="test-app",
        app_display_name="Test App",
        app_description="An app used only in tests.",
        contract_version="1.3",
        get_version=lambda: "9.9.9",
        get_build_date=lambda: "2026-01-01T00:00:00Z",
        get_uptime_seconds=lambda: 42,
        db_probe=lambda: db_probe_return,
        icon_path=str(icon),
    )
    app = Flask(__name__)
    app.register_blueprint(bp)
    app.config.update(TESTING=True)
    return app


def test_health_returns_required_fields(tmp_path):
    app = _make_app(tmp_path)
    resp = app.test_client().get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {
        "status": "ok", "version": "9.9.9",
        "uptime_seconds": 42, "db": "ok",
    }


def test_health_still_200_when_db_is_error(tmp_path):
    app = _make_app(tmp_path, db_probe_return="error")
    resp = app.test_client().get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["db"] == "error"


def test_version_payload(tmp_path):
    app = _make_app(tmp_path)
    resp = app.test_client().get("/version")
    assert resp.status_code == 200
    assert resp.get_json() == {
        "app": "test-app", "version": "9.9.9",
        "built": "2026-01-01T00:00:00Z", "contract": "1.3",
        "display_name": "Test App",
        "description": "An app used only in tests.",
    }


def test_icon_returns_png(tmp_path):
    app = _make_app(tmp_path)
    resp = app.test_client().get("/icon")
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"
    assert resp.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_icon_404_when_missing(tmp_path):
    app = _make_app(tmp_path, icon_exists=False)
    resp = app.test_client().get("/icon")
    assert resp.status_code == 404


def test_icon_path_can_be_a_callable(tmp_path):
    """Late-binding for the icon path: the resolver is invoked per-request
    so apps can re-point the icon at runtime (e.g. tests that patch a
    module-level constant)."""
    good = tmp_path / "good.png"
    good.write_bytes(b"\x89PNG\r\n\x1a\n")
    state = {"target": good}

    bp = create_health_blueprint(
        app_name="x", app_display_name="X", app_description="",
        contract_version="1.3",
        get_version=lambda: "0", get_build_date=lambda: "0",
        get_uptime_seconds=lambda: 0,
        db_probe=lambda: "ok",
        icon_path=lambda: state["target"],
    )
    app = Flask(__name__)
    app.register_blueprint(bp)
    client = app.test_client()

    assert client.get("/icon").status_code == 200
    state["target"] = tmp_path / "gone.png"
    assert client.get("/icon").status_code == 404


def test_shutdown_404_when_token_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("CONTER_SHUTDOWN_TOKEN", raising=False)
    app = _make_app(tmp_path)
    resp = app.test_client().post("/shutdown")
    assert resp.status_code == 404


def test_shutdown_401_without_bearer(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTER_SHUTDOWN_TOKEN", "s3cr3t")
    app = _make_app(tmp_path)
    resp = app.test_client().post("/shutdown")
    assert resp.status_code == 401


def test_shutdown_401_with_wrong_token(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTER_SHUTDOWN_TOKEN", "s3cr3t")
    app = _make_app(tmp_path)
    resp = app.test_client().post(
        "/shutdown", headers={"Authorization": "Bearer nope"}
    )
    assert resp.status_code == 401


def test_shutdown_200_with_valid_token(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTER_SHUTDOWN_TOKEN", "s3cr3t")
    monkeypatch.setenv("CONTER_SHUTDOWN_TOKEN_TEST_NO_EXIT", "1")
    app = _make_app(tmp_path)
    resp = app.test_client().post(
        "/shutdown", headers={"Authorization": "Bearer s3cr3t"}
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


def test_endpoint_names_match_documented_public_endpoints(tmp_path):
    """Apps list these four names in PUBLIC_ENDPOINTS to bypass their
    auth gate — keeping them stable is part of the library contract."""
    app = _make_app(tmp_path)
    names = {r.endpoint for r in app.url_map.iter_rules()
             if r.endpoint != "static"}
    assert names == {
        "health.health_check", "health.version_info",
        "health.icon", "health.shutdown",
    }
