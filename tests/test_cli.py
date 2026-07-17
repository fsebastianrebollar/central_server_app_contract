"""Unit tests for `central_server_app_contract.contract.cli`.

These cover the argparse wiring + env-var propagation in isolation —
no Flask app, no subprocess — so breakage is attributed to the library,
not to any specific consumer.
"""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import pytest

from central_server_app_contract.contract import cli


# ---------------------------------------------------------------------------
# build_parser
# ---------------------------------------------------------------------------

def test_build_parser_defaults():
    p = cli.build_parser()
    args = p.parse_args([])
    assert args.headless is False
    assert args.host == "127.0.0.1"
    assert args.port == 5000
    assert args.log_level == "INFO"
    assert args.data_dir is None
    assert args.shutdown_token is None
    assert args.prefix == ""
    assert args.info is False
    assert args.version is False


def test_build_parser_accepts_custom_host_port_defaults():
    p = cli.build_parser(default_host="0.0.0.0", default_port=9000)
    args = p.parse_args([])
    assert args.host == "0.0.0.0"
    assert args.port == 9000


def test_build_parser_rejects_invalid_log_level():
    p = cli.build_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["--log-level", "TRACE"])


def test_build_parser_log_level_reads_conter_env(monkeypatch):
    monkeypatch.setenv("CONTER_LOG_LEVEL", "DEBUG")
    p = cli.build_parser()
    assert p.parse_args([]).log_level == "DEBUG"


def test_build_parser_log_level_falls_back_to_legacy_env(monkeypatch):
    """Legacy LOG_LEVEL env still honoured for pre-v1.1 deployments."""
    monkeypatch.delenv("CONTER_LOG_LEVEL", raising=False)
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    p = cli.build_parser()
    assert p.parse_args([]).log_level == "WARNING"


def test_build_parser_log_level_cli_beats_env(monkeypatch):
    monkeypatch.setenv("CONTER_LOG_LEVEL", "DEBUG")
    p = cli.build_parser()
    assert p.parse_args(["--log-level", "ERROR"]).log_level == "ERROR"


def test_build_parser_allows_app_specific_extras():
    """Apps extend the parser with their own flags; they must co-exist."""
    p = cli.build_parser()
    p.add_argument("--desktop", action="store_true")
    args = p.parse_args(["--desktop", "--headless", "--port", "8000"])
    assert args.desktop is True
    assert args.headless is True
    assert args.port == 8000


# ---------------------------------------------------------------------------
# handle_preboot_flags
# ---------------------------------------------------------------------------

_META = dict(
    get_version=lambda: "1.2.3",
    app_name="demo-app",
    display_name="Demo App",
    description="Demo application.",
    contract_version="1.3",
)


def test_handle_preboot_flags_noop_when_neither_set():
    p = cli.build_parser()
    args = p.parse_args([])
    # Must return normally — no SystemExit.
    cli.handle_preboot_flags(args, **_META)


def test_handle_preboot_flags_version_prints_and_exits(capsys):
    p = cli.build_parser()
    args = p.parse_args(["--version"])
    with pytest.raises(SystemExit) as excinfo:
        cli.handle_preboot_flags(args, **_META)
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == "1.2.3"


def test_handle_preboot_flags_info_prints_json_and_exits():
    p = cli.build_parser()
    args = p.parse_args(["--info"])
    buf = io.StringIO()
    with pytest.raises(SystemExit) as excinfo, redirect_stdout(buf):
        cli.handle_preboot_flags(args, **_META)
    assert excinfo.value.code == 0
    data = json.loads(buf.getvalue())
    assert data == {
        "app": "demo-app",
        "display_name": "Demo App",
        "description": "Demo application.",
        "contract": "1.3",
        "version": "1.2.3",
    }


# ---------------------------------------------------------------------------
# apply_contract_env
# ---------------------------------------------------------------------------

def _clean_env(monkeypatch):
    """Scrub CONTER_* and LOG_LEVEL so we observe exactly what the helper sets."""
    for k in ("CONTER_DATA_DIR", "CONTER_SHUTDOWN_TOKEN",
              "CONTER_URL_PREFIX", "LOG_LEVEL", "CONTER_LOG_LEVEL",
              "CONTER_AUTH_URL", "CONTER_AUTH_KEY", "CONTER_SSO_SECRET"):
        monkeypatch.delenv(k, raising=False)


def test_apply_contract_env_sets_log_level_always(monkeypatch):
    _clean_env(monkeypatch)
    args = cli.build_parser().parse_args(["--log-level", "WARNING"])
    cli.apply_contract_env(args)
    import os
    assert os.environ["LOG_LEVEL"] == "WARNING"


def test_apply_contract_env_propagates_data_dir(monkeypatch, tmp_path):
    _clean_env(monkeypatch)
    target = tmp_path / "runtime"
    args = cli.build_parser().parse_args(["--data-dir", str(target)])
    cli.apply_contract_env(args)
    import os
    assert os.environ["CONTER_DATA_DIR"] == str(target.resolve())
    assert target.is_dir(), "helper must create the directory"


def test_apply_contract_env_skips_data_dir_when_unset(monkeypatch):
    _clean_env(monkeypatch)
    args = cli.build_parser().parse_args([])
    cli.apply_contract_env(args)
    import os
    assert "CONTER_DATA_DIR" not in os.environ


def test_apply_contract_env_propagates_shutdown_token(monkeypatch):
    _clean_env(monkeypatch)
    args = cli.build_parser().parse_args(["--shutdown-token", "tok"])
    cli.apply_contract_env(args)
    import os
    assert os.environ["CONTER_SHUTDOWN_TOKEN"] == "tok"


def test_apply_contract_env_propagates_prefix(monkeypatch):
    _clean_env(monkeypatch)
    args = cli.build_parser().parse_args(["--prefix", "/services/demo"])
    cli.apply_contract_env(args)
    import os
    assert os.environ["CONTER_URL_PREFIX"] == "/services/demo"


def test_apply_contract_env_skips_empty_prefix(monkeypatch):
    _clean_env(monkeypatch)
    args = cli.build_parser().parse_args([])
    cli.apply_contract_env(args)
    import os
    assert "CONTER_URL_PREFIX" not in os.environ


def test_apply_contract_env_propagates_auth_flags(monkeypatch):
    _clean_env(monkeypatch)
    args = cli.build_parser().parse_args([
        "--auth-url", "http://127.0.0.1:5000/",
        "--auth-key", "svc-key",
        "--sso-secret", "sso-sec",
    ])
    cli.apply_contract_env(args)
    import os
    assert os.environ["CONTER_AUTH_URL"] == "http://127.0.0.1:5000"
    assert os.environ["CONTER_AUTH_KEY"] == "svc-key"
    assert os.environ["CONTER_SSO_SECRET"] == "sso-sec"


def test_apply_contract_env_skips_auth_flags_when_unset(monkeypatch):
    _clean_env(monkeypatch)
    args = cli.build_parser().parse_args([])
    cli.apply_contract_env(args)
    import os
    assert "CONTER_AUTH_URL" not in os.environ
    assert "CONTER_AUTH_KEY" not in os.environ
    assert "CONTER_SSO_SECRET" not in os.environ


# ---------------------------------------------------------------------------
# normalize_prefix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("", ""),
    ("   ", ""),
    ("/services/demo", "/services/demo"),
    ("services/demo", "/services/demo"),
    ("/services/demo/", "/services/demo"),
    ("/services/demo///", "/services/demo"),
    ("  /services/demo/  ", "/services/demo"),
])
def test_normalize_prefix(raw, expected):
    assert cli.normalize_prefix(raw) == expected
