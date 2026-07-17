"""Unit tests for `central_server_app_contract.version`.

App-level tests in conter-stats (`tests/unit/test_version.py`) still
verify that `app/version.py` produces the right constants and
delegates correctly — those are the consumer contract. These tests
cover the library plumbing directly: bundled-file reads, pyproject
parsing, the fallback chain and the uptime helper.
"""
from __future__ import annotations

import sys
import time

import pytest

from central_server_app_contract import version as libver


# ---------------------------------------------------------------------------
# read_bundled_text_file
# ---------------------------------------------------------------------------

class TestReadBundledTextFile:
    def test_none_when_not_frozen(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        assert libver.read_bundled_text_file("version.txt") is None

    def test_reads_from_meipass(self, monkeypatch, tmp_path):
        (tmp_path / "version.txt").write_text("9.9.9\n")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        assert libver.read_bundled_text_file("version.txt") == "9.9.9"

    def test_none_when_file_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        assert libver.read_bundled_text_file("missing.txt") is None

    def test_none_when_file_is_empty(self, monkeypatch, tmp_path):
        (tmp_path / "version.txt").write_text("   \n")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        assert libver.read_bundled_text_file("version.txt") is None


# ---------------------------------------------------------------------------
# read_pyproject_version
# ---------------------------------------------------------------------------

class TestReadPyprojectVersion:
    def test_none_when_file_missing(self, tmp_path):
        assert libver.read_pyproject_version(tmp_path / "nope.toml") is None

    def test_reads_project_version(self, tmp_path):
        f = tmp_path / "pyproject.toml"
        f.write_text('[project]\nname = "x"\nversion = "1.2.3"\n')
        assert libver.read_pyproject_version(f) == "1.2.3"

    def test_none_when_no_project_section(self, tmp_path):
        f = tmp_path / "pyproject.toml"
        f.write_text('[build-system]\nrequires = ["setuptools"]\n')
        assert libver.read_pyproject_version(f) is None

    def test_none_when_version_is_missing(self, tmp_path):
        f = tmp_path / "pyproject.toml"
        f.write_text('[project]\nname = "x"\n')
        assert libver.read_pyproject_version(f) is None

    def test_none_when_toml_is_malformed(self, tmp_path):
        """Malformed TOML must not propagate — fallback takes over."""
        f = tmp_path / "pyproject.toml"
        f.write_text("[project\nthis is not toml\n")
        assert libver.read_pyproject_version(f) is None

    def test_accepts_path_as_string(self, tmp_path):
        f = tmp_path / "pyproject.toml"
        f.write_text('[project]\nname = "x"\nversion = "0.0.1"\n')
        assert libver.read_pyproject_version(str(f)) == "0.0.1"


# ---------------------------------------------------------------------------
# resolve_version
# ---------------------------------------------------------------------------

class TestResolveVersion:
    def test_bundled_wins_over_pyproject(self, monkeypatch, tmp_path):
        (tmp_path / "version.txt").write_text("7.7.7")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        pyproj = tmp_path / "pyproject.toml"
        pyproj.write_text('[project]\nname = "x"\nversion = "1.0.0"\n')
        assert libver.resolve_version(pyproj) == "7.7.7"

    def test_falls_back_to_pyproject_when_not_frozen(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        pyproj = tmp_path / "pyproject.toml"
        pyproj.write_text('[project]\nname = "x"\nversion = "1.0.0"\n')
        assert libver.resolve_version(pyproj) == "1.0.0"

    def test_final_fallback_when_nothing_available(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        assert libver.resolve_version(tmp_path / "nope.toml") == "dev"

    def test_fallback_is_configurable(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        assert libver.resolve_version(
            tmp_path / "nope.toml", fallback="unknown"
        ) == "unknown"


# ---------------------------------------------------------------------------
# resolve_build_date
# ---------------------------------------------------------------------------

class TestResolveBuildDate:
    def test_dev_fallback_when_not_frozen(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        assert libver.resolve_build_date() == "dev"

    def test_reads_from_bundle(self, monkeypatch, tmp_path):
        (tmp_path / "build_date.txt").write_text("2026-04-22")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        assert libver.resolve_build_date() == "2026-04-22"

    def test_fallback_when_bundle_has_no_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        assert libver.resolve_build_date() == "dev"


# ---------------------------------------------------------------------------
# get_uptime_seconds
# ---------------------------------------------------------------------------

class TestUptime:
    def test_is_non_negative_integer(self):
        assert libver.get_uptime_seconds(time.time()) >= 0

    def test_grows_with_elapsed_time(self):
        t0 = time.time() - 10
        assert libver.get_uptime_seconds(t0) >= 10

    def test_zero_when_start_is_now(self):
        assert libver.get_uptime_seconds(time.time()) == 0
