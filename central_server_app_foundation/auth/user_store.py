"""SQLite-backed user store — the core of the auth chassis.

`UserStore` owns the schema migration, the bootstrap admin seed, and
every CRUD path an app's `/user`, `/login` and `/admin/users/...`
routes need. Keeping it class-based means each consumer binds its own
`db_path` / `admin_user` / `admin_pass` / translator once and exposes
bound methods as module-level callables — preserving the historical
`from app.services.auth_service import authenticate` surface.
"""
from __future__ import annotations

import sqlite3
from typing import Callable

from werkzeug.security import check_password_hash, generate_password_hash


VALID_ROLES = ("operator", "supervisor", "admin")


def can_publish(role: str) -> bool:
    """Supervisors and admins can publish public workspaces.

    Stateless helper — doesn't need a UserStore instance. Lives here
    because the role taxonomy does.
    """
    return role in ("supervisor", "admin")


def _default_gettext(string: str, **variables) -> str:
    """Identity translator — returns the raw string after %-formatting.

    Matches `flask_babel.gettext`'s signature so apps with Babel can
    drop it in without a wrapper: `gettext=flask_babel.gettext`.
    """
    return string % variables if variables else string


class UserStore:
    """All the SQL for the users table, bound to one DB + bootstrap admin.

    Parameters are keyword-only so call sites read as configuration,
    not positional plumbing.

    - `db_path` — absolute SQLite path, or a callable returning one.
      Accepting a callable lets tests monkeypatch a module-level
      `_DB_PATH` and have every subsequent call see the new value.
    - `admin_user` / `admin_pass` — bootstrap credentials, seeded by
      `init_schema()` on first boot and refused by `delete_user()` /
      role-demotion to keep a recovery path.
    - `valid_roles` — the role taxonomy. Defaults to
      `("operator", "supervisor", "admin")` which every current
      Conter app uses; passed in so future apps can widen it without
      patching the library.
    - `gettext` — optional translator matching `flask_babel.gettext`'s
      signature. Identity by default so the library works without
      Babel; apps with i18n pass `flask_babel.gettext` and get
      translated error messages via `raise ValueError(_(...))`.
    """

    is_remote = False

    def __init__(
        self,
        *,
        db_path: str | Callable[[], str],
        admin_user: str,
        admin_pass: str,
        valid_roles: tuple[str, ...] = VALID_ROLES,
        gettext: Callable[..., str] = _default_gettext,
    ) -> None:
        if callable(db_path):
            self._db_path_resolver: Callable[[], str] = db_path
        else:
            self._db_path_resolver = lambda p=db_path: p
        self._admin_user = admin_user
        self._admin_pass = admin_pass
        self._valid_roles = tuple(valid_roles)
        self._ = gettext

    @property
    def valid_roles(self) -> tuple[str, ...]:
        """Public read-only view of the role taxonomy (used by templates)."""
        return self._valid_roles

    # ---- connection + schema --------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path_resolver())
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "  username TEXT PRIMARY KEY,"
            "  password_hash TEXT NOT NULL,"
            "  is_admin INTEGER NOT NULL DEFAULT 0"
            ")"
        )
        # Add role column if missing; backfill from is_admin so upgrades
        # from the pre-role schema don't lose the admin bit.
        cols = {row[1] for row in conn.execute(
            "PRAGMA table_info(users)"
        ).fetchall()}
        if "role" not in cols:
            conn.execute(
                "ALTER TABLE users ADD COLUMN role TEXT NOT NULL "
                "DEFAULT 'operator'"
            )
            conn.execute("UPDATE users SET role='admin' WHERE is_admin=1")
            conn.commit()
        return conn

    def init_schema(self) -> None:
        """Create the users table and seed the bootstrap admin."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT 1 FROM users WHERE username = ?",
                (self._admin_user,),
            ).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO users (username, password_hash, "
                    "is_admin, role) VALUES (?, ?, 1, 'admin')",
                    (self._admin_user,
                     generate_password_hash(self._admin_pass)),
                )
                conn.commit()
        finally:
            conn.close()

    # ---- credential checks ----------------------------------------------

    def authenticate(self, username: str, password: str) -> dict | None:
        """Verify credentials. Returns user dict or None."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT username, password_hash, is_admin, role "
                "FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if row and check_password_hash(row[1], password):
                role = row[3] or ("admin" if row[2] else "operator")
                return {
                    "username": row[0],
                    "is_admin": role == "admin",
                    "role": role,
                }
            return None
        finally:
            conn.close()

    # ---- user CRUD ------------------------------------------------------

    def create_user(self, username: str, password: str) -> None:
        """Create a new user. Raises ValueError if username exists."""
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT 1 FROM users WHERE username = ?", (username,),
            ).fetchone()
            if existing:
                raise ValueError(self._(
                    'User "%(username)s" already exists.',
                    username=username,
                ))
            conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, "
                "role) VALUES (?, ?, 0, 'operator')",
                (username, generate_password_hash(password)),
            )
            conn.commit()
        finally:
            conn.close()

    def delete_user(self, username: str) -> None:
        """Delete a user. Refuses to delete the bootstrap admin."""
        if username == self._admin_user:
            raise ValueError(self._("Cannot delete the admin user."))
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM users WHERE username = ?", (username,),
            )
            conn.commit()
        finally:
            conn.close()

    def change_password(self, username: str, new_password: str) -> None:
        """Set a new password hash for the given user."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                (generate_password_hash(new_password), username),
            )
            conn.commit()
        finally:
            conn.close()

    # ---- role management ------------------------------------------------

    def set_role(self, username: str, role: str) -> None:
        """Assign a role. Refuses to demote the bootstrap admin."""
        if role not in self._valid_roles:
            raise ValueError(self._("Invalid role: %(role)s", role=role))
        if username == self._admin_user and role != "admin":
            raise ValueError(self._(
                "Cannot demote the bootstrap admin user."
            ))
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT 1 FROM users WHERE username = ?", (username,),
            ).fetchone()
            if not row:
                raise ValueError(self._(
                    'User "%(username)s" not found.',
                    username=username,
                ))
            is_admin = 1 if role == "admin" else 0
            conn.execute(
                "UPDATE users SET role = ?, is_admin = ? "
                "WHERE username = ?",
                (role, is_admin, username),
            )
            conn.commit()
        finally:
            conn.close()

    def get_role(self, username: str) -> str:
        """Return the user's role, defaulting to operator for unknowns."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT role, is_admin FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if not row:
                return "operator"
            return row[0] or ("admin" if row[1] else "operator")
        finally:
            conn.close()

    # ---- listing --------------------------------------------------------

    def list_users(self) -> list[dict]:
        """Return all users sorted by username."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT username, is_admin, role FROM users "
                "ORDER BY username"
            ).fetchall()
            return [
                {
                    "username": r[0],
                    "is_admin": bool(r[1]),
                    "role": r[2] or ("admin" if r[1] else "operator"),
                }
                for r in rows
            ]
        finally:
            conn.close()
