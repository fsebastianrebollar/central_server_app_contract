"""Version + build-date + uptime helpers for Conter apps.

Each app keeps its own `app/version.py` so it owns the `APP_NAME`,
`APP_DISPLAY_NAME`, `APP_DESCRIPTION` and `CONTRACT_VERSION` constants
— those are identity, not plumbing. The plumbing (resolve a semver
string from a PyInstaller bundle or a `pyproject.toml`, resolve a
build date, track uptime) lives here so every app resolves the same
way.

Resolution order for `resolve_version()`:

1. `version.txt` bundled inside PyInstaller's `sys._MEIPASS`
   (populated by the release spec for frozen builds).
2. `[project].version` in the app's `pyproject.toml` (source builds).
3. Literal `"dev"` as last-resort fallback.

`resolve_build_date()` follows the same pattern with `build_date.txt`
and falls back to `"dev"`.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path


def read_bundled_text_file(name: str) -> str | None:
    """Read a small text file from `sys._MEIPASS` when running frozen.

    Returns `None` when not in a PyInstaller bundle or when the file is
    missing / empty. Used for `version.txt` and `build_date.txt`, both
    of which are written at build time by the release spec.
    """
    if not getattr(sys, "frozen", False):
        return None
    candidate = Path(sys._MEIPASS) / name
    if not candidate.exists():
        return None
    return candidate.read_text(encoding="utf-8").strip() or None


def read_pyproject_version(pyproject_path: Path | str) -> str | None:
    """Return `[project].version` from a `pyproject.toml`, or None.

    Swallows every error (missing file, malformed TOML, missing key)
    because this is a metadata helper — the caller already has a
    fallback. Requires Python 3.11+ (`tomllib` in stdlib).
    """
    try:
        import tomllib
    except ImportError:
        return None
    path = Path(pyproject_path)
    if not path.exists():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    v = data.get("project", {}).get("version")
    return v if isinstance(v, str) and v else None


def resolve_version(
    pyproject_path: Path | str,
    *,
    bundled_name: str = "version.txt",
    fallback: str = "dev",
) -> str:
    """Canonical version string for a Conter app.

    Chain: PyInstaller bundle → pyproject → fallback. The fallback is
    configurable so tests can assert failure modes without polluting
    the sentinel.
    """
    return (
        read_bundled_text_file(bundled_name)
        or read_pyproject_version(pyproject_path)
        or fallback
    )


def resolve_build_date(
    *,
    bundled_name: str = "build_date.txt",
    fallback: str = "dev",
) -> str:
    """Build date (`YYYY-MM-DD`) for frozen builds, fallback otherwise.

    Source builds don't have a build date — returning the same sentinel
    as `resolve_version()` keeps the `/version` payload coherent.
    """
    return read_bundled_text_file(bundled_name) or fallback


def get_uptime_seconds(start_time: float) -> int:
    """Whole seconds elapsed since `start_time` (typically captured at
    app-module import so it survives hot reloads)."""
    return int(time.time() - start_time)
