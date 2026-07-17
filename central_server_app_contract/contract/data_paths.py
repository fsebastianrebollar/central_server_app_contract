"""Supervisor contract — optional `CONTER_DATA_DIR` override.

When the supervisor (or the operator) starts the app with
``python run.py --data-dir /path/to/data``, every writable artefact
(SQLite DBs, on-disk caches, report JSONs, wiki uploads) lives under
that single directory. The CLI scaffold in `contract.cli` takes care of
setting ``CONTER_DATA_DIR`` before ``create_app()`` runs; this module
is what services call when they resolve their paths.

When ``--data-dir`` is absent the helpers here return ``None`` and each
service falls back to its pre-contract resolution logic unchanged —
deploys that don't opt in see zero behavioural change.

Read-only assets (``certs/``, ``translations/``, ``version.txt``,
``build_date.txt``) are NOT affected — they ship with the bundle.
"""
from __future__ import annotations

import os


_ENV_VAR = "CONTER_DATA_DIR"


def get_data_dir() -> str | None:
    """Return the override data directory, or None if unset.

    Empty strings and whitespace are treated as unset so that
    ``CONTER_DATA_DIR=""`` does not silently point writes at the CWD.
    """
    value = os.environ.get(_ENV_VAR, "").strip()
    return value or None


def override_path(subpath: str) -> str | None:
    """Join `subpath` under the data-dir override. Returns None if no override.

    Creates the containing directory on demand so callers can treat the
    returned path as ready-to-use. When ``subpath`` itself names a
    directory (e.g. ``"cache"``), that directory is created; when it
    names a file (``"settings.db"``), its parent directory is created.
    """
    base = get_data_dir()
    if not base:
        return None
    target = os.path.join(base, subpath) if subpath else base
    parent = target if _looks_like_dir(subpath) else os.path.dirname(target)
    os.makedirs(parent or base, exist_ok=True)
    return target


def _looks_like_dir(subpath: str) -> bool:
    """Heuristic: treat `subpath` as a directory when it has no extension.

    Good enough for the canonical call sites (``settings.db`` → file,
    ``cache`` / ``reports`` / ``wiki_uploads`` → directory).
    """
    if not subpath:
        return True
    return os.path.splitext(os.path.basename(subpath))[1] == ""
