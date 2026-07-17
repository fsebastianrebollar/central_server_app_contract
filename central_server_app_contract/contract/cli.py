"""Supervisor-contract CLI helpers.

Every Conter app exposes the same contract flags to `conter_central_server`:

    --headless --host --port --log-level --data-dir
    --shutdown-token --prefix --info --version
    --auth-url --auth-key --sso-secret          (v1.4)

This module ships the parser and the env-var propagation so each app's
`run.py` only adds its own app-specific flags (e.g. `--desktop` for
apps that ship a pywebview window) and hands control back.

Typical usage:

    from central_server_app_contract.contract.cli import (
        build_parser, handle_preboot_flags, apply_contract_env,
    )

    parser = build_parser(description="Conter Stats — Web & Desktop")
    parser.add_argument("--desktop", action="store_true", ...)  # app-only
    args = parser.parse_args()

    handle_preboot_flags(
        args,
        get_version=get_version,
        app_name=APP_NAME,
        display_name=APP_DISPLAY_NAME,
        description=APP_DESCRIPTION,
        contract_version=CONTRACT_VERSION,
    )  # exits 0 for --version / --info, returns otherwise

    apply_contract_env(args)  # sets CONTER_* env vars from args

    from app import create_app      # safe: env is primed before import
    app = create_app()
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Callable


VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


def build_parser(
    *,
    description: str = "Conter app",
    default_host: str = "127.0.0.1",
    default_port: int = 5000,
) -> argparse.ArgumentParser:
    """Build an argparse parser pre-loaded with every contract flag.

    The app is expected to `add_argument()` its own extras on top (e.g.
    `--desktop`) before calling `parse_args()`.
    """
    parser = argparse.ArgumentParser(description=description)

    parser.add_argument(
        "--headless",
        action="store_true",
        help="Explicit web-only mode. Required by conter_central_server "
        "when the app runs under supervision.",
    )
    parser.add_argument(
        "--host",
        default=default_host,
        help=f"Interface to bind to (default {default_host}). "
        "Use 0.0.0.0 to expose on the LAN.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=default_port,
        help=f"Port to run on (default {default_port}).",
    )
    parser.add_argument(
        "--log-level",
        # CLI flag > CONTER_LOG_LEVEL (v1.1) > legacy LOG_LEVEL > INFO.
        default=(
            os.environ.get("CONTER_LOG_LEVEL")
            or os.environ.get("LOG_LEVEL")
            or "INFO"
        ),
        choices=VALID_LOG_LEVELS,
        help="Logging level (default INFO). Also reads CONTER_LOG_LEVEL "
        "(v1.1) or legacy LOG_LEVEL from the environment.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Base directory for writable data (settings.db, cache/, "
        "reports/, wiki_uploads/). If omitted, each subsystem uses its "
        "legacy per-platform default.",
    )
    parser.add_argument(
        "--shutdown-token",
        default=None,
        help="Bearer token for POST /shutdown. When omitted the endpoint "
        "returns 404 and the supervisor falls back to SIGTERM (v1.1).",
    )
    parser.add_argument(
        "--prefix",
        default="",
        help="URL prefix when running behind the central server reverse "
        "proxy (e.g. /services/<app>). Configures APPLICATION_ROOT so "
        "url_for() and cookies use the correct path (v1.3).",
    )
    parser.add_argument(
        "--auth-url",
        default=None,
        help="Base URL of the Conter Central auth API (e.g. "
        "http://127.0.0.1:5000). When set, credentials are verified "
        "against the Central instead of the local user DB (v1.4).",
    )
    parser.add_argument(
        "--auth-key",
        default=None,
        help="Service key (bearer token) authenticating this app "
        "against the Central auth API (v1.4).",
    )
    parser.add_argument(
        "--sso-secret",
        default=None,
        help="Shared secret to validate the Central's SSO cookie. "
        "When set, the app's own login is replaced by single sign-on "
        "through the Central (v1.4).",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Print app metadata as JSON and exit (v1.2). No Flask boot, "
        "no DB touched.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print version and exit.",
    )
    return parser


def handle_preboot_flags(
    args: argparse.Namespace,
    *,
    get_version: Callable[[], str],
    app_name: str,
    display_name: str,
    description: str,
    contract_version: str,
) -> None:
    """Short-circuit `--version` / `--info` before the app imports Flask.

    Both flags must never trigger a DB connection or open a port — the
    supervisor calls them during service-registration to discover
    metadata cheaply. We exit straight after printing so the caller
    doesn't even reach `from app import create_app`.
    """
    if getattr(args, "version", False):
        print(get_version())
        sys.exit(0)

    if getattr(args, "info", False):
        payload = {
            "app": app_name,
            "display_name": display_name,
            "description": description,
            "contract": contract_version,
            "version": get_version(),
        }
        print(json.dumps(payload))
        sys.exit(0)


def apply_contract_env(args: argparse.Namespace) -> None:
    """Propagate parsed contract flags to the `CONTER_*` env vars.

    Must be called BEFORE `from app import create_app` because several
    service modules resolve their paths (`_DB_PATH`, `UPLOADS_DIR`) at
    import time, and the Flask factory reads `CONTER_URL_PREFIX` at the
    top of `create_app()`.
    """
    # --log-level always propagates — `create_app()` reads LOG_LEVEL.
    log_level = getattr(args, "log_level", None) or "INFO"
    os.environ["LOG_LEVEL"] = log_level

    data_dir = getattr(args, "data_dir", None)
    if data_dir:
        abs_dir = os.path.abspath(data_dir)
        os.makedirs(abs_dir, exist_ok=True)
        os.environ["CONTER_DATA_DIR"] = abs_dir

    shutdown_token = getattr(args, "shutdown_token", None)
    if shutdown_token:
        os.environ["CONTER_SHUTDOWN_TOKEN"] = shutdown_token

    prefix = normalize_prefix(getattr(args, "prefix", "") or "")
    if prefix:
        os.environ["CONTER_URL_PREFIX"] = prefix

    auth_url = getattr(args, "auth_url", None)
    if auth_url:
        os.environ["CONTER_AUTH_URL"] = auth_url.rstrip("/")

    auth_key = getattr(args, "auth_key", None)
    if auth_key:
        os.environ["CONTER_AUTH_KEY"] = auth_key

    sso_secret = getattr(args, "sso_secret", None)
    if sso_secret:
        os.environ["CONTER_SSO_SECRET"] = sso_secret


def normalize_prefix(raw: str) -> str:
    """Reduce a user-typed prefix to canonical form.

    Accepts `services/app`, `/services/app`, `/services/app/` and always
    returns `/services/app` (or `""` for empty input). Centralising this
    means the parser, the env var and the Flask factory can't disagree.
    """
    prefix = (raw or "").strip()
    if not prefix:
        return ""
    if not prefix.startswith("/"):
        prefix = "/" + prefix
    return prefix.rstrip("/")
