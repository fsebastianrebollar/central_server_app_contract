"""Auth blueprint factory — login / logout / user profile / admin CRUD.

See `central_server_app_foundation.auth_ui.__init__` for the overall rationale. This
module wires the routes and keeps everything injectable so that:

- Translations come through an optional `gettext=` callable (falls back
  to identity, so apps without flask_babel still work).
- User preferences (theme, language, anything else the app saves per
  user) flow through `get_user_pref` / `set_user_pref` callables the
  app hands in. No hard dependency on a specific settings store.
- App-specific session hydration beyond identity keys happens through
  `on_login_hook(user, session)`. The library guarantees `user_id`,
  `is_admin`, `is_guest` and `role` are set before the hook runs.
- Redirect targets are parameterised (`post_login_endpoint`,
  `user_profile_endpoint`) because apps own their main landing page.

The blueprint is always named `auth` so existing `url_for("auth.login")`
call sites in the chassis (design blueprint, public-endpoints set,
language switcher) work unchanged.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from urllib.parse import urlsplit

from central_server_app_foundation.auth import UserStore


def _safe_next_url(raw: str) -> str:
    """Validate a post-login redirect target against open-redirect abuse.

    Accepts relative paths and absolute http(s) URLs whose hostname
    matches the one the browser used for this request — any port. The
    port latitude is deliberate: Conter apps share one host on
    different ports and the SSO flow bounces between them.
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw.startswith("/") and not raw.startswith("//"):
        return raw
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return ""
    if parts.hostname != request.host.split(":")[0]:
        return ""
    return raw


def _identity(s: str, **_kwargs: Any) -> str:
    """Gettext fallback when flask_babel isn't installed.

    Accepts keyword arguments because some callers pass `username=` /
    `role=` for interpolation; we do a best-effort `%`-style format so
    the resulting string still embeds the values.
    """
    if not _kwargs:
        return s
    try:
        return s % _kwargs
    except (KeyError, TypeError, ValueError):
        return s


def _current_user() -> str:
    return session.get("user_id", "") or ""


def _is_admin() -> bool:
    return bool(session.get("is_admin"))


def _is_guest() -> bool:
    return bool(session.get("is_guest"))


def create_auth_blueprint(
    *,
    user_store: UserStore,
    post_login_endpoint: str,
    user_profile_endpoint: str = "auth.user_profile",
    login_endpoint: str = "auth.login",
    gettext: Callable[..., str] | None = None,
    supported_languages: Sequence[str] = ("en",),
    default_language: str = "en",
    allow_guest: bool = True,
    get_user_pref: Callable[[str, str, str], str] | None = None,
    set_user_pref: Callable[[str, str, str], None] | None = None,
    on_login_hook: Callable[[dict, Any], None] | None = None,
    login_brand_short: str = "",
    login_brand_full: str = "",
    login_stylesheet_urls: Sequence[str | tuple[str, str]] = (),
    login_favicon_url: str | tuple[str, str] = "",
    login_template: str = "central_server_app_foundation/auth/login.html",
    user_template: str = "central_server_app_foundation/auth/user.html",
    protected_user: str = "",
    url_prefix: str | None = None,
) -> Blueprint:
    """Build the auth blueprint.

    Parameters
    ----------
    user_store
        The `UserStore` instance (already bound to the app's auth DB).
    post_login_endpoint
        Flask endpoint to redirect to after a successful login, e.g.
        `"main.dashboard"`. The app owns its landing page.
    gettext
        Optional translator. Defaults to an identity function that
        interpolates `%(name)s`-style kwargs so flash messages still
        render user/role names even without babel.
    allow_guest
        When `False`, `/login/guest` returns 404. Apps without a guest
        mode should set this explicitly.
    get_user_pref / set_user_pref
        Callables that persist user-scoped preferences. Used by the
        `/api/theme` and `/lang/<lang>` endpoints to remember choices
        across sessions. When `None`, those endpoints still work in
        the current session but don't persist.
    on_login_hook
        Called after identity keys are set on login: signature
        `hook(user: dict, session)`. Use it to hydrate app-specific
        session state (theme, locale, workspace defaults, …).

    The returned blueprint exposes every route the original
    conter-stats auth blueprint had, under the same endpoint names
    (`auth.login`, `auth.logout`, `auth.user_profile`, `auth.set_theme`,
    `auth.set_language`, etc.).
    """
    bp = Blueprint(
        "auth",
        __name__,
        url_prefix=url_prefix,
        template_folder="templates",
    )

    gt = gettext or _identity
    langs = tuple(supported_languages)

    # Make `_` available inside library templates. If flask_babel is
    # installed it already binds `_` as a Jinja global — our context
    # processor only kicks in as a fallback so the template doesn't
    # raise NameError on apps without babel.
    @bp.app_context_processor
    def _inject_gettext_fallback():
        return {"_": gt} if "_" not in current_app.jinja_env.globals else {}

    def _resolve(ref: str | tuple[str, str]) -> str:
        """Resolve a URL spec to a path, honouring the app's URL prefix.

        Plain strings are returned as-is (they may already be absolute or
        external). Tuples are passed to `url_for` so `APPLICATION_ROOT`
        prefixing (v1.3 reverse-proxy deployments) works transparently.
        """
        if isinstance(ref, tuple):
            endpoint, filename = ref
            try:
                return url_for(endpoint, filename=filename)
            except Exception:
                return ""
        return ref

    @bp.app_context_processor
    def _inject_login_chrome():
        try:
            chassis_css = url_for("design.static", filename="style.css")
        except Exception:
            chassis_css = None
        return {
            "auth_login_brand_short": login_brand_short,
            "auth_login_brand_full": login_brand_full,
            "auth_login_stylesheet_urls": [
                u for u in (_resolve(r) for r in login_stylesheet_urls) if u
            ],
            "auth_login_favicon_url": _resolve(login_favicon_url),
            "auth_login_allow_guest": allow_guest,
            "auth_protected_user": protected_user,
            "auth_chassis_css_url": chassis_css,
            "auth_users_managed_centrally": bool(
                getattr(user_store, "is_remote", False)
            ),
        }

    # --- Login / logout ----------------------------------------------------

    @bp.route("/login", methods=["GET", "POST"])
    def login():
        next_url = _safe_next_url(
            request.form.get("next") or request.args.get("next") or ""
        )
        if session.get("user_id"):
            return redirect(next_url or url_for(post_login_endpoint))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = user_store.authenticate(username, password)
            if user is None:
                flash(gt("Invalid username or password."), "error")
                return render_template(login_template, auth_login_next=next_url)
            _set_identity(user)
            if on_login_hook is not None:
                try:
                    on_login_hook(user, session)
                except Exception:
                    current_app.logger.exception("auth on_login_hook failed")
            return redirect(next_url or url_for(post_login_endpoint))

        return render_template(login_template, auth_login_next=next_url)

    @bp.route("/login/guest")
    def login_guest():
        if not allow_guest:
            return (gt("Not available."), 404)
        session["user_id"] = "guest"
        session["is_admin"] = False
        session["is_guest"] = True
        session["role"] = "guest"
        return redirect(url_for(post_login_endpoint))

    @bp.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for(login_endpoint))

    # --- User profile ------------------------------------------------------

    @bp.route("/user")
    def user_profile():
        if _is_guest() or not _is_admin():
            users: list[dict] = []
        else:
            users = user_store.list_users()
        return render_template(
            user_template,
            users=users,
            valid_roles=user_store.valid_roles,
        )

    # --- Form-based admin + own-password -----------------------------------

    @bp.route("/change-password", methods=["POST"])
    def change_own_password():
        if _is_guest():
            flash(gt("Access denied."), "error")
            return redirect(url_for(user_profile_endpoint))
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not new_password:
            flash(gt("New password cannot be empty."), "error")
            return redirect(url_for(user_profile_endpoint))
        if new_password != confirm_password:
            flash(gt("Passwords do not match."), "error")
            return redirect(url_for(user_profile_endpoint))
        if user_store.authenticate(_current_user(), current_password) is None:
            flash(gt("Current password is incorrect."), "error")
            return redirect(url_for(user_profile_endpoint))
        user_store.change_password(_current_user(), new_password)
        flash(gt("Password changed successfully."), "success")
        return redirect(url_for(user_profile_endpoint))

    @bp.route("/admin/users/create", methods=["POST"])
    def admin_create_user():
        if not _is_admin():
            flash(gt("Access denied."), "error")
            return redirect(url_for(user_profile_endpoint))
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            flash(gt("Username and password are required."), "error")
            return redirect(url_for(user_profile_endpoint))
        try:
            user_store.create_user(username, password)
            flash(
                gt('User "%(username)s" created.', username=username),
                "success",
            )
        except ValueError as e:
            flash(str(e), "error")
        return redirect(url_for(user_profile_endpoint))

    @bp.route("/admin/users/<username>/delete", methods=["POST"])
    def admin_delete_user(username):
        if not _is_admin():
            flash(gt("Access denied."), "error")
            return redirect(url_for(user_profile_endpoint))
        try:
            user_store.delete_user(username)
            flash(
                gt('User "%(username)s" deleted.', username=username),
                "success",
            )
        except ValueError as e:
            flash(str(e), "error")
        return redirect(url_for(user_profile_endpoint))

    @bp.route("/admin/users/<username>/role", methods=["POST"])
    def admin_set_role(username):
        if not _is_admin():
            flash(gt("Access denied."), "error")
            return redirect(url_for(user_profile_endpoint))
        role = request.form.get("role", "").strip()
        if role not in user_store.valid_roles:
            flash(gt("Invalid role."), "error")
            return redirect(url_for(user_profile_endpoint))
        try:
            user_store.set_role(username, role)
            flash(
                gt(
                    'Role for "%(username)s" set to %(role)s.',
                    username=username,
                    role=role,
                ),
                "success",
            )
        except ValueError as e:
            flash(str(e), "error")
        return redirect(url_for(user_profile_endpoint))

    @bp.route("/admin/users/<username>/change-password", methods=["POST"])
    def admin_change_password(username):
        if not _is_admin() and username != _current_user():
            flash(gt("Access denied."), "error")
            return redirect(url_for(user_profile_endpoint))
        new_password = request.form.get("new_password", "")
        if not new_password:
            flash(gt("Password cannot be empty."), "error")
            return redirect(url_for(user_profile_endpoint))
        user_store.change_password(username, new_password)
        flash(
            gt(
                'Password changed for "%(username)s".', username=username
            ),
            "success",
        )
        return redirect(url_for(user_profile_endpoint))

    # --- JSON / API --------------------------------------------------------

    @bp.route("/api/user/change-password", methods=["POST"])
    def api_change_own_password():
        if _is_guest():
            return jsonify({"error": "Access denied."}), 403
        data = request.get_json(force=True) or {}
        current_password = data.get("current_password", "")
        new_password = data.get("new_password", "")
        confirm_password = data.get("confirm_password", "")
        if not new_password:
            return jsonify({"error": "New password cannot be empty."}), 400
        if new_password != confirm_password:
            return jsonify({"error": "Passwords do not match."}), 400
        if user_store.authenticate(_current_user(), current_password) is None:
            return jsonify({"error": "Current password is incorrect."}), 400
        user_store.change_password(_current_user(), new_password)
        return jsonify({"ok": True})

    @bp.route("/api/admin/users/create", methods=["POST"])
    def api_admin_create_user():
        if not _is_admin():
            return jsonify({"error": "Access denied."}), 403
        data = request.get_json(force=True) or {}
        username = data.get("username", "").strip()
        password = data.get("password", "")
        if not username or not password:
            return jsonify({"error": "Username and password are required."}), 400
        try:
            user_store.create_user(username, password)
            return jsonify({"ok": True})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @bp.route("/api/admin/users/<username>/delete", methods=["POST"])
    def api_admin_delete_user(username):
        if not _is_admin():
            return jsonify({"error": "Access denied."}), 403
        try:
            user_store.delete_user(username)
            return jsonify({"ok": True})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @bp.route("/api/admin/users/<username>/role", methods=["POST"])
    def api_admin_set_role(username):
        if not _is_admin():
            return jsonify({"error": "Access denied."}), 403
        data = request.get_json(force=True) or {}
        role = data.get("role", "").strip()
        if role not in user_store.valid_roles:
            return jsonify({"error": "Invalid role."}), 400
        try:
            user_store.set_role(username, role)
            return jsonify({"ok": True})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @bp.route("/api/admin/users/<username>/change-password", methods=["POST"])
    def api_admin_change_password(username):
        if not _is_admin() and username != _current_user():
            return jsonify({"error": "Access denied."}), 403
        data = request.get_json(force=True) or {}
        new_password = data.get("new_password", "")
        if not new_password:
            return jsonify({"error": "Password cannot be empty."}), 400
        user_store.change_password(username, new_password)
        return jsonify({"ok": True})

    # --- Theme + language --------------------------------------------------

    @bp.route("/api/theme", methods=["POST"])
    def set_theme():
        data = request.get_json(silent=True) or {}
        theme = data.get("theme", "dark")
        session["theme"] = theme
        user = _current_user()
        if user and not _is_guest() and set_user_pref is not None:
            try:
                set_user_pref(user, "theme", theme)
            except Exception:
                current_app.logger.exception("theme pref persist failed")
        return jsonify({"ok": True})

    @bp.route("/lang/<lang>")
    def set_language(lang):
        if lang not in langs:
            lang = default_language
        session["lang"] = lang
        user = _current_user()
        if user and not _is_guest() and set_user_pref is not None:
            try:
                set_user_pref(user, "lang", lang)
            except Exception:
                current_app.logger.exception("lang pref persist failed")
        try:
            fallback = url_for(post_login_endpoint)
        except Exception:
            fallback = "/"
        referer = request.referrer or fallback
        resp = make_response(redirect(referer))
        resp.set_cookie("lang", lang, max_age=365 * 24 * 3600, samesite="Lax")
        return resp

    # --- helpers -----------------------------------------------------------

    def _set_identity(user: dict) -> None:
        session["user_id"] = user["username"]
        session["is_admin"] = bool(user.get("is_admin"))
        session["role"] = user.get("role", "operator")
        session["is_guest"] = False
        if get_user_pref is not None:
            try:
                session["theme"] = get_user_pref(
                    user["username"], "theme", ""
                )
                session["lang"] = get_user_pref(
                    user["username"], "lang", ""
                )
            except Exception:
                current_app.logger.exception("auth pref read failed")

    return bp
