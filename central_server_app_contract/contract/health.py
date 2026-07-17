"""Supervisor contract blueprint factory — `/health`, `/version`, `/icon`, `/shutdown`.

Each app calls `create_health_blueprint(...)` from its Flask factory and
registers the returned blueprint. All four endpoints are public; the
app's auth gate is expected to allow them through via a `PUBLIC_ENDPOINTS`
set. The endpoint names are fixed (`health.health_check`, `health.version_info`,
`health.icon`, `health.shutdown`) so apps can hardcode them in that set.
"""
from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Callable

from flask import Blueprint, jsonify, request, send_file


logger = logging.getLogger(__name__)


_SHUTDOWN_TOKEN_ENV = "CONTER_SHUTDOWN_TOKEN"
_SHUTDOWN_TEST_NO_EXIT_ENV = "CONTER_SHUTDOWN_TOKEN_TEST_NO_EXIT"


def create_health_blueprint(
    *,
    app_name: str,
    app_display_name: str,
    app_description: str,
    contract_version: str,
    get_version: Callable[[], str],
    get_build_date: Callable[[], str],
    get_uptime_seconds: Callable[[], int],
    db_probe: Callable[[], str],
    icon_path: Path | str | Callable[[], Path | str],
) -> Blueprint:
    """Build the supervisor-contract blueprint for this app.

    Parameters mirror the contract v1.3 `/version` payload plus the
    callbacks each app implements differently:

    - `db_probe()` must return `"ok" | "error" | "n/a"` without raising.
      It's called from `/health` on every request, so it must be fast
      (target < 100 ms) and swallow its own errors.
    - `icon_path` is a path (or callable returning one) to a PNG served
      by `/icon`. Non-existent → endpoint returns 404. Accepting a
      callable lets apps do late path resolution (important for tests
      that monkeypatch the path's source-of-truth at the module level).
    - `get_version` / `get_build_date` / `get_uptime_seconds` are app-
      supplied so frozen/source builds can resolve differently.
    """
    if callable(icon_path):
        _icon_path_resolver: Callable[[], Path] = lambda: Path(icon_path())
    else:
        _fixed = Path(icon_path)
        _icon_path_resolver = lambda: _fixed

    bp = Blueprint("health", __name__)

    @bp.get("/health")
    def health_check():
        return jsonify(
            {
                "status": "ok",
                "version": get_version(),
                "uptime_seconds": get_uptime_seconds(),
                "db": db_probe(),
            }
        )

    @bp.get("/version")
    def version_info():
        return jsonify(
            {
                "app": app_name,
                "version": get_version(),
                "built": get_build_date(),
                "contract": contract_version,
                "display_name": app_display_name,
                "description": app_description,
            }
        )

    @bp.get("/icon")
    def icon():
        path = _icon_path_resolver()
        if not path.is_file():
            return jsonify({"error": "not found"}), 404
        return send_file(str(path), mimetype="image/png")

    @bp.post("/shutdown")
    def shutdown():
        expected = os.environ.get(_SHUTDOWN_TOKEN_ENV, "")
        if not expected:
            return jsonify({"error": "not found"}), 404

        auth = request.headers.get("Authorization", "")
        prefix = "Bearer "
        if not auth.startswith(prefix):
            return jsonify({"error": "unauthorized"}), 401
        provided = auth[len(prefix):]
        if not secrets.compare_digest(provided, expected):
            return jsonify({"error": "unauthorized"}), 401

        logger.info("Shutdown requested via supervisor contract /shutdown")

        def _exit_later():
            time.sleep(0.2)
            os._exit(0)

        if not os.environ.get(_SHUTDOWN_TEST_NO_EXIT_ENV):
            threading.Thread(target=_exit_later, daemon=True).start()

        return jsonify({"ok": True})

    return bp
