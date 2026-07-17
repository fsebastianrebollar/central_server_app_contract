"""Unit tests for `central_server_app_contract.contract.data_paths`.

Library-level coverage for the `CONTER_DATA_DIR` resolver. App-level
tests in conter-stats still verify that each service (`settings_service`,
`cache_service`, …) honours the override — those live in
`tests/unit/test_data_paths.py::TestServicePathsHonourOverride`.
"""
from __future__ import annotations

import os

import pytest

from central_server_app_contract.contract import data_paths


# ---------------------------------------------------------------------------
# get_data_dir
# ---------------------------------------------------------------------------

class TestGetDataDir:
    def test_returns_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("CONTER_DATA_DIR", raising=False)
        assert data_paths.get_data_dir() is None

    def test_returns_value_when_set(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CONTER_DATA_DIR", str(tmp_path))
        assert data_paths.get_data_dir() == str(tmp_path)

    def test_empty_string_treated_as_unset(self, monkeypatch):
        """A blank env value must not silently redirect writes to the CWD."""
        monkeypatch.setenv("CONTER_DATA_DIR", "")
        assert data_paths.get_data_dir() is None

    def test_whitespace_only_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("CONTER_DATA_DIR", "   ")
        assert data_paths.get_data_dir() is None

    def test_surrounding_whitespace_is_stripped(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CONTER_DATA_DIR", f"  {tmp_path}  ")
        assert data_paths.get_data_dir() == str(tmp_path)


# ---------------------------------------------------------------------------
# override_path
# ---------------------------------------------------------------------------

class TestOverridePath:
    def test_returns_none_without_override(self, monkeypatch):
        monkeypatch.delenv("CONTER_DATA_DIR", raising=False)
        assert data_paths.override_path("settings.db") is None

    def test_joins_file_under_base(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CONTER_DATA_DIR", str(tmp_path))
        assert data_paths.override_path("settings.db") == str(
            tmp_path / "settings.db"
        )

    def test_joins_dir_under_base(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CONTER_DATA_DIR", str(tmp_path))
        assert data_paths.override_path("cache") == str(tmp_path / "cache")

    def test_creates_parent_for_file(self, monkeypatch, tmp_path):
        """Callers expect the parent directory to exist so SQLite can open."""
        nested = tmp_path / "nested" / "deeper"
        monkeypatch.setenv("CONTER_DATA_DIR", str(nested))
        path = data_paths.override_path("settings.db")
        assert os.path.isdir(os.path.dirname(path))

    def test_creates_directory_for_dir_subpath(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CONTER_DATA_DIR", str(tmp_path))
        path = data_paths.override_path("cache")
        assert os.path.isdir(path)

    def test_creates_nested_directory(self, monkeypatch, tmp_path):
        """`wiki_uploads` under a base that doesn't yet exist — mkdir -p."""
        base = tmp_path / "does-not-exist-yet"
        monkeypatch.setenv("CONTER_DATA_DIR", str(base))
        path = data_paths.override_path("wiki_uploads")
        assert os.path.isdir(path)

    def test_empty_subpath_returns_base(self, monkeypatch, tmp_path):
        """`override_path("")` returns the data-dir itself (not a file)."""
        monkeypatch.setenv("CONTER_DATA_DIR", str(tmp_path))
        assert data_paths.override_path("") == str(tmp_path)
        assert os.path.isdir(str(tmp_path))


# ---------------------------------------------------------------------------
# Directory heuristic
# ---------------------------------------------------------------------------

class TestLooksLikeDir:
    """`_looks_like_dir` is internal but the semantics are load-bearing —
    get it wrong and we'd create `settings.db/` as a directory."""

    @pytest.mark.parametrize("subpath", [
        "cache", "reports", "wiki_uploads", "some/deep/dir",
    ])
    def test_treats_extensionless_as_dir(self, subpath):
        assert data_paths._looks_like_dir(subpath) is True

    @pytest.mark.parametrize("subpath", [
        "settings.db", "auth.sqlite", "nested/report.json",
    ])
    def test_treats_file_with_ext_as_file(self, subpath):
        assert data_paths._looks_like_dir(subpath) is False

    def test_empty_is_treated_as_dir(self):
        assert data_paths._looks_like_dir("") is True
