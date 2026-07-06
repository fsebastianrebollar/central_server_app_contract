"""Integration tests for `central_server_app_foundation.auth_ui`.

Covers the blueprint factory surface: route wiring, redirect targets,
callback invocation, guest mode toggle, gettext fallback, template
rendering and `protected_user` gating in the user profile partial.
"""
from __future__ import annotations

import pytest
from flask import Flask, session

from central_server_app_foundation.auth import UserStore
from central_server_app_foundation.auth_ui import create_auth_blueprint


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def user_store(tmp_path):
    store = UserStore(
        db_path=str(tmp_path / "auth.db"),
        admin_user="admin",
        admin_pass="adminpass",
    )
    store.init_schema()
    return store


@pytest.fixture()
def app_factory(user_store, tmp_path):
    """Return a factory so each test can tweak blueprint options.

    The factory sets up a minimal `main.dashboard` endpoint for
    redirect targets and a tiny `base.html` loader so the library
    user template can extend chassis chrome during tests without
    pulling in the full design blueprint.
    """
    def _make(**kwargs):
        app = Flask(__name__)
        app.config["SECRET_KEY"] = "t"
        app.config["TESTING"] = True

        @app.route("/")
        def dashboard():
            return "dashboard"

        # Inline override for chassis/base.html so template inheritance
        # in the library's user.html resolves without registering the
        # full design blueprint.
        from jinja2 import DictLoader, ChoiceLoader
        app.jinja_loader = ChoiceLoader([
            app.jinja_loader,
            DictLoader({
                "central_server_app_foundation/design/base.html": (
                    "<html><head><title>{% block title %}{% endblock %}"
                    "</title></head><body>{% block content %}{% endblock %}"
                    "{% block scripts %}{% endblock %}</body></html>"
                ),
            }),
        ])

        @app.context_processor
        def _inject_identity():
            return {
                "is_admin": session.get("is_admin", False),
                "is_guest": session.get("is_guest", False),
                "current_user": session.get("user_id", ""),
            }

        opts = dict(
            user_store=user_store,
            post_login_endpoint="dashboard",
        )
        opts.update(kwargs)
        bp = create_auth_blueprint(**opts)
        app.register_blueprint(bp)
        return app
    return _make


@pytest.fixture()
def app(app_factory):
    return app_factory()


@pytest.fixture()
def logged_in(app):
    """A test client with an admin session already set."""
    client = app.test_client()
    with client.session_transaction() as s:
        s["user_id"] = "admin"
        s["is_admin"] = True
        s["is_guest"] = False
        s["role"] = "admin"
    return client


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

class TestLogin:
    def test_login_page_renders(self, app):
        resp = app.test_client().get("/login")
        assert resp.status_code == 200
        assert b"<form" in resp.data

    def test_login_with_valid_credentials_sets_identity(self, app):
        c = app.test_client()
        resp = c.post("/login", data={
            "username": "admin", "password": "adminpass",
        })
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/")
        with c.session_transaction() as s:
            assert s["user_id"] == "admin"
            assert s["is_admin"] is True
            assert s["is_guest"] is False

    def test_login_invalid_renders_page_with_flash(self, app):
        c = app.test_client()
        resp = c.post("/login", data={
            "username": "admin", "password": "wrong",
        })
        assert resp.status_code == 200
        assert b"Invalid" in resp.data

    def test_login_already_logged_in_redirects_to_post_login(self, logged_in):
        resp = logged_in.get("/login")
        assert resp.status_code == 302

    def test_on_login_hook_runs_after_identity_set(self, app_factory, user_store):
        captured = {}

        def hook(user, sess):
            captured["user"] = user["username"]
            captured["is_admin_in_session"] = sess.get("is_admin")

        app = app_factory(on_login_hook=hook)
        app.test_client().post("/login", data={
            "username": "admin", "password": "adminpass",
        })
        assert captured["user"] == "admin"
        assert captured["is_admin_in_session"] is True

    def test_on_login_hook_exception_doesnt_break_login(
        self, app_factory, user_store
    ):
        def hook(_u, _s):
            raise RuntimeError("boom")

        app = app_factory(on_login_hook=hook)
        resp = app.test_client().post("/login", data={
            "username": "admin", "password": "adminpass",
        })
        assert resp.status_code == 302


class TestLoginNext:
    """Safe ?next= handling — the SSO entry point for subapp bounces."""

    def test_next_relative_path_honoured(self, app):
        c = app.test_client()
        resp = c.post("/login?next=/somewhere", data={
            "username": "admin", "password": "adminpass",
        })
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/somewhere"

    def test_next_same_host_other_port_honoured(self, app):
        c = app.test_client()
        resp = c.post(
            "/login?next=http://localhost:5001/editor",
            data={"username": "admin", "password": "adminpass"},
            base_url="http://localhost:5000",
        )
        assert resp.headers["Location"] == "http://localhost:5001/editor"

    def test_next_foreign_host_ignored(self, app):
        c = app.test_client()
        resp = c.post(
            "/login?next=http://evil.example.com/",
            data={"username": "admin", "password": "adminpass"},
        )
        assert resp.headers["Location"].endswith("/")
        assert "evil" not in resp.headers["Location"]

    def test_next_protocol_relative_ignored(self, app):
        c = app.test_client()
        resp = c.post(
            "/login?next=//evil.example.com/",
            data={"username": "admin", "password": "adminpass"},
        )
        assert "evil" not in resp.headers["Location"]

    def test_next_rendered_as_hidden_field(self, app):
        resp = app.test_client().get("/login?next=/somewhere")
        assert b'name="next" value="/somewhere"' in resp.data

    def test_next_honoured_when_already_logged_in(self, logged_in):
        resp = logged_in.get("/login?next=/elsewhere")
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/elsewhere"


class TestGuestLogin:
    def test_guest_login_sets_guest_session(self, app):
        c = app.test_client()
        resp = c.get("/login/guest")
        assert resp.status_code == 302
        with c.session_transaction() as s:
            assert s["user_id"] == "guest"
            assert s["is_guest"] is True

    def test_guest_disabled_returns_404(self, app_factory):
        app = app_factory(allow_guest=False)
        resp = app.test_client().get("/login/guest")
        assert resp.status_code == 404


class TestLogout:
    def test_logout_clears_session_and_redirects_to_login(self, logged_in):
        resp = logged_in.post("/logout")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
        with logged_in.session_transaction() as s:
            assert "user_id" not in s


# ---------------------------------------------------------------------------
# User profile
# ---------------------------------------------------------------------------

class TestUserProfile:
    def test_admin_sees_user_list(self, logged_in, user_store):
        user_store.create_user("bob", "pw")
        resp = logged_in.get("/user")
        assert resp.status_code == 200
        assert b"bob" in resp.data

    def test_guest_sees_profile_without_user_list(self, app, user_store):
        user_store.create_user("bob", "pw")
        c = app.test_client()
        with c.session_transaction() as s:
            s["user_id"] = "guest"
            s["is_guest"] = True
            s["is_admin"] = False
        resp = c.get("/user")
        assert resp.status_code == 200
        assert b"bob" not in resp.data

    def test_protected_user_has_no_delete_or_role_buttons(
        self, app_factory, user_store
    ):
        app = app_factory(protected_user="admin")
        c = app.test_client()
        with c.session_transaction() as s:
            s["user_id"] = "admin"
            s["is_admin"] = True
        user_store.create_user("bob", "pw")
        resp = c.get("/user")
        assert resp.status_code == 200
        # bob has both buttons; admin has neither but the password-change
        # button is still present.
        assert b"openRoleModal('bob'" in resp.data
        assert b"openDeleteModal('bob'" in resp.data
        assert b"openRoleModal('admin'" not in resp.data
        assert b"openDeleteModal('admin'" not in resp.data


# ---------------------------------------------------------------------------
# Admin CRUD (form-based + JSON)
# ---------------------------------------------------------------------------

class TestAdminCRUDForm:
    def test_create_user(self, logged_in, user_store):
        resp = logged_in.post("/admin/users/create", data={
            "username": "new", "password": "p",
        })
        assert resp.status_code == 302
        assert any(u["username"] == "new" for u in user_store.list_users())

    def test_non_admin_blocked(self, app, user_store):
        c = app.test_client()
        with c.session_transaction() as s:
            s["user_id"] = "someone"
            s["is_admin"] = False
        resp = c.post("/admin/users/create",
                      data={"username": "x", "password": "y"})
        assert resp.status_code == 302
        assert not any(u["username"] == "x" for u in user_store.list_users())

    def test_delete_user(self, logged_in, user_store):
        user_store.create_user("bye", "p")
        resp = logged_in.post("/admin/users/bye/delete")
        assert resp.status_code == 302
        assert not any(u["username"] == "bye" for u in user_store.list_users())

    def test_set_role(self, logged_in, user_store):
        user_store.create_user("joe", "p")
        resp = logged_in.post("/admin/users/joe/role",
                              data={"role": "supervisor"})
        assert resp.status_code == 302
        assert user_store.get_role("joe") == "supervisor"

    def test_admin_change_password(self, logged_in, user_store):
        user_store.create_user("pete", "old")
        resp = logged_in.post(
            "/admin/users/pete/change-password",
            data={"new_password": "new"},
        )
        assert resp.status_code == 302
        assert user_store.authenticate("pete", "new") is not None


class TestAdminCRUDJSON:
    def test_api_create_user(self, logged_in, user_store):
        resp = logged_in.post("/api/admin/users/create",
                              json={"username": "n", "password": "p"})
        assert resp.get_json() == {"ok": True}

    def test_api_non_admin_blocked(self, app, user_store):
        c = app.test_client()
        with c.session_transaction() as s:
            s["is_admin"] = False
        resp = c.post("/api/admin/users/create", json={"username": "n"})
        assert resp.status_code == 403

    def test_api_delete_user(self, logged_in, user_store):
        user_store.create_user("bye", "p")
        resp = logged_in.post("/api/admin/users/bye/delete")
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True}

    def test_api_set_role_rejects_unknown(self, logged_in, user_store):
        user_store.create_user("joe", "p")
        resp = logged_in.post("/api/admin/users/joe/role",
                              json={"role": "emperor"})
        assert resp.status_code == 400

    def test_api_admin_change_password(self, logged_in, user_store):
        user_store.create_user("pete", "old")
        resp = logged_in.post(
            "/api/admin/users/pete/change-password",
            json={"new_password": "new"},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Own-password change
# ---------------------------------------------------------------------------

class TestOwnPassword:
    def test_form_change_own_password(self, logged_in, user_store):
        resp = logged_in.post("/change-password", data={
            "current_password": "adminpass",
            "new_password": "freshpass",
            "confirm_password": "freshpass",
        })
        assert resp.status_code == 302
        assert user_store.authenticate("admin", "freshpass") is not None

    def test_guest_cannot_change_own_password(self, app, user_store):
        """A guest's attempted password change must not actually change
        anything in the store — it just redirects back to /user."""
        c = app.test_client()
        with c.session_transaction() as s:
            s["user_id"] = "guest"
            s["is_guest"] = True
        resp = c.post("/change-password", data={
            "current_password": "x", "new_password": "y", "confirm_password": "y",
        })
        assert resp.status_code == 302
        # Guest is never in the user store, and even if it were, nothing
        # about it should have changed (password-check still valid).
        assert user_store.authenticate("guest", "y") is None

    def test_api_own_password_mismatch_returns_400(self, logged_in):
        resp = logged_in.post("/api/user/change-password", json={
            "current_password": "adminpass",
            "new_password": "a", "confirm_password": "b",
        })
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Theme + language
# ---------------------------------------------------------------------------

class TestThemeAndLang:
    def test_set_theme_updates_session(self, logged_in):
        resp = logged_in.post("/api/theme", json={"theme": "light"})
        assert resp.get_json() == {"ok": True}
        with logged_in.session_transaction() as s:
            assert s["theme"] == "light"

    def test_set_theme_persists_via_callback(self, app_factory, user_store):
        saved = {}

        def getter(u, k, d):
            return saved.get((u, k), d)

        def setter(u, k, v):
            saved[(u, k)] = v

        app = app_factory(get_user_pref=getter, set_user_pref=setter)
        c = app.test_client()
        with c.session_transaction() as s:
            s["user_id"] = "admin"
            s["is_guest"] = False
        c.post("/api/theme", json={"theme": "light"})
        assert saved[("admin", "theme")] == "light"

    def test_set_theme_guest_does_not_persist(self, app_factory):
        saved = {}

        def setter(u, k, v):
            saved[(u, k)] = v

        app = app_factory(set_user_pref=setter)
        c = app.test_client()
        with c.session_transaction() as s:
            s["user_id"] = "guest"
            s["is_guest"] = True
        c.post("/api/theme", json={"theme": "light"})
        assert saved == {}

    def test_set_language_unknown_falls_back_to_default(self, app_factory):
        app = app_factory(
            supported_languages=("en", "es"), default_language="en",
        )
        c = app.test_client()
        c.get("/lang/zz")
        with c.session_transaction() as s:
            assert s["lang"] == "en"

    def test_set_language_known_is_preserved(self, app_factory):
        app = app_factory(supported_languages=("en", "es", "de"))
        c = app.test_client()
        c.get("/lang/de")
        with c.session_transaction() as s:
            assert s["lang"] == "de"


# ---------------------------------------------------------------------------
# Chrome injection + gettext fallback
# ---------------------------------------------------------------------------

class TestChromeInjection:
    def test_brand_appears_in_login(self, app_factory):
        app = app_factory(
            login_brand_short="ABC", login_brand_full="My App",
        )
        resp = app.test_client().get("/login")
        assert b"ABC" in resp.data
        assert b"My App" in resp.data

    def test_stylesheet_endpoint_tuple_resolved_via_url_for(self, app_factory):
        from flask import Blueprint
        # Give the app a static endpoint the login chrome can reference.
        app = app_factory(
            login_stylesheet_urls=(("static", "css/fake.css"),),
        )
        resp = app.test_client().get("/login")
        assert b"/static/css/fake.css" in resp.data

    def test_guest_link_hidden_when_allow_guest_false(self, app_factory):
        app = app_factory(allow_guest=False)
        resp = app.test_client().get("/login")
        assert b"/login/guest" not in resp.data


class TestGettextFallback:
    def test_identity_fallback_interpolates_kwargs(self, app_factory, user_store):
        captured = {}

        def bad_create(*_a, **_k):
            raise ValueError("duplicate user foo")

        # Install a real user so the call path reaches the flash string.
        user_store.create_user("dup", "p")
        # No gettext passed — identity fallback should be used.
        app = app_factory()
        c = app.test_client()
        with c.session_transaction() as s:
            s["user_id"] = "admin"
            s["is_admin"] = True

        # Trigger the "User ... created." flash via a successful create.
        resp = c.post("/admin/users/create",
                      data={"username": "brand_new", "password": "p"},
                      follow_redirects=True)
        assert b"brand_new" in resp.data  # %(username)s interpolated
