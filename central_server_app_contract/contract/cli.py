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

# La precedencia que el contrato promete desde v1.1: flag > CONTER_LOG_LEVEL
# > LOG_LEVEL. Exportada porque `control_foundation.resolve_cli_level` la
# necesita y NO puede conocerla: `CONTER_*` es un prefijo de marca, y el
# chassis es genérico por regla. Sin esto, cada app copia el literal y el
# día que se añada una variable hay que acordarse de las tres.
LOG_LEVEL_ENV_VARS = ("CONTER_LOG_LEVEL", "LOG_LEVEL")
LOG_LEVEL_FLAGS = ("--log-level",)


def requested_log_level(args: "argparse.Namespace | None" = None, *,
                        argv: "list[str] | None" = None) -> "str | None":
    """El nivel de log **solo si alguien lo pidió**; si no, ``None``.

    "Lo pidió" = el flag aparece en la línea de comandos (en su forma
    exacta: `--log-level X` o `--log-level=X`) o hay una de las variables
    de :data:`LOG_LEVEL_ENV_VARS` puesta con un nivel válido — y entonces
    manda el valor de la **variable**, no el default del parser.

    Existe porque `--log-level` tiene `default="INFO"`, así que
    `args.log_level` viene relleno SIEMPRE y no distingue "me pidieron
    INFO" de "nadie dijo nada". Esa diferencia decide si el nivel pisa la
    sección ``[logging]`` del `.conf` — la que el operador edita desde
    Settings— o si manda el fichero.
    """
    argumentos = list(sys.argv[1:] if argv is None else argv)
    if any(a == f or a.startswith(f + "=")
           for a in argumentos for f in LOG_LEVEL_FLAGS):
        nivel = getattr(args, "log_level", None) if args is not None else None
        if nivel in VALID_LOG_LEVELS:
            return nivel
    for var in LOG_LEVEL_ENV_VARS:
        valor = (os.environ.get(var) or "").strip().upper()
        if valor in VALID_LOG_LEVELS:
            return valor
    return None


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


def apply_contract_env(args: argparse.Namespace, *,
                       argv: "list[str] | None" = None) -> None:
    """Propagate parsed contract flags to the `CONTER_*` env vars.

    `argv` existe para los tests y para quien parsee una línea de comandos
    que no sea `sys.argv`: es lo que se mira para saber si el nivel de log
    se pidió de verdad.

    Must be called BEFORE `from app import create_app` because several
    service modules resolve their paths (`_DB_PATH`, `UPLOADS_DIR`) at
    import time, and the Flask factory reads `CONTER_URL_PREFIX` at the
    top of `create_app()`.
    """
    # El nivel se propaga SOLO si alguien lo pidió.
    #
    # Exportarlo siempre —lo que se hacía hasta v0.5— reintroducía en toda
    # app CONTER el fallo que `control_foundation` 1.12 vino a matar: su
    # `resolve_cli_level` mira el entorno para decidir si el operador pidió
    # un nivel, y con `LOG_LEVEL` puesta en cada arranque concluía que sí.
    # Resultado: la sección `[logging]` del `.conf` quedaba decorativa — el
    # operador la editaba desde Settings, guardaba, y no pasaba nada. Sin
    # error y sin test rojo.
    #
    # Y la trampa era peor de lo que parece, porque depende del ORDEN:
    # `apply_contract_env` se llama pronto (propaga --data-dir y --prefix),
    # así que llegaba antes que el resolver salvo que la app supiera
    # invertirlos a propósito.
    #
    # Compatibilidad: una app que lea `LOG_LEVEL` a pelo ya no la encuentra
    # cuando nadie pidió nivel. Su default es el mismo `INFO` que se
    # exportaba, así que el comportamiento observable no cambia; lo que
    # cambia es que deja de mentir sobre quién lo pidió.
    log_level = requested_log_level(args, argv=argv)
    if log_level:
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
