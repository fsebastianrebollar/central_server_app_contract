import argparse
import json
import pytest
from flask import Flask
from central_server_app_contract.contract.cli import handle_preboot_flags
from central_server_app_contract.contract.health import create_health_blueprint
from central_server_app_contract.contract.metadata import normalize_descriptions


def test_normalize_ignores_malformed_metadata():
    assert normalize_descriptions(None) == {}
    assert normalize_descriptions(["es"]) == {}
    assert normalize_descriptions({"es_ES": " Español ", "de": "", "en": 3,
                                   "bad key": "bad", 1: "bad"}) == {"es-es": "Español"}


@pytest.mark.parametrize("translations", [None, {"en": "Files", "es": "Ficheros"}])
def test_cli_http_metadata_match_and_keep_legacy_fallback(translations, capsys, tmp_path):
    args = argparse.Namespace(info=True, version=False)
    with pytest.raises(SystemExit):
        handle_preboot_flags(args, get_version=lambda: "1.0", app_name="demo",
                             display_name="Demo", description="Files", contract_version="1.5",
                             descriptions=translations)
    cli = json.loads(capsys.readouterr().out)
    app = Flask(__name__)
    app.register_blueprint(create_health_blueprint(app_name="demo", app_display_name="Demo",
        app_description="Files", app_descriptions=translations, contract_version="1.5",
        get_version=lambda: "1.0", get_build_date=lambda: "dev", get_uptime_seconds=lambda: 0,
        db_probe=lambda: "ok", icon_path=tmp_path / "icon.png"))
    http = app.test_client().get("/version").json
    assert cli["description"] == http["description"] == "Files"
    if translations is None:
        assert "descriptions" not in cli and "descriptions" not in http
    else:
        assert cli["descriptions"] == http["descriptions"] == translations
