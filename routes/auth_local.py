"""
Local authentication: username/password login and logout.
Entra ID login/callback is handled by identity.flask.Auth (registered in app.py).
"""
import logging
from flask import (
    Blueprint, render_template, request, session, redirect,
    url_for, flash, current_app
)
from werkzeug.security import check_password_hash
from routes import resolve_user_session

logger = logging.getLogger(__name__)

auth_local_bp = Blueprint("auth_local", __name__)


def _local_auth_enabled():
    store = current_app.config.get("APP_SETTINGS_STORE")
    if store:
        try:
            return store.get_setting("local_auth_enabled", "false").lower() == "true"
        except Exception:
            pass
    cfg = current_app.config.get("APP_CONFIG", {})
    return cfg.get("local_auth_enabled", False)


@auth_local_bp.route("/login", methods=["GET", "POST"])
def login():
    # If user is already logged in, go to dashboard
    if "user" in session:
        return redirect(url_for("dashboard.index"))

    # Check if Entra ID is configured as the auth method
    auth = current_app.config.get("AUTH")
    store = current_app.config.get("APP_SETTINGS_STORE")
    entra_enabled = False
    local_enabled = _local_auth_enabled()

    if store:
        try:
            entra_enabled = store.get_setting("entra_enabled", "false").lower() == "true"
        except Exception:
            pass

    if request.method == "GET":
        return render_template(
            "login.html",
            entra_enabled=entra_enabled,
            local_enabled=local_enabled,
        )

    # POST: local login
    if not local_enabled:
        flash("Local authentication is not enabled.", "danger")
        return render_template("login.html", entra_enabled=entra_enabled, local_enabled=False)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        flash("Username and password are required.", "warning")
        return render_template("login.html", entra_enabled=entra_enabled, local_enabled=True)

    user_store = current_app.config.get("USER_STORE")
    if not user_store:
        flash("User store not configured. Check Azure Storage connection.", "danger")
        return render_template("login.html", entra_enabled=entra_enabled, local_enabled=True)

    user = user_store.get_user_by_username(username)
    if not user or not user.get("is_active"):
        flash("Invalid username or password.", "danger")
        return render_template("login.html", entra_enabled=entra_enabled, local_enabled=True)

    if not check_password_hash(user.get("password_hash", ""), password):
        flash("Invalid username or password.", "danger")
        return render_template("login.html", entra_enabled=entra_enabled, local_enabled=True)

    session["user"] = resolve_user_session(user, user_store)
    logger.info("Local login: %s (role: %s)", username, session["user"].get("role_name"))
    next_url = request.args.get("next") or url_for("dashboard.index")
    return redirect(next_url)


@auth_local_bp.route("/logout")
def logout():
    session.clear()
    # If Entra ID is active, redirect to Entra logout too
    auth = current_app.config.get("AUTH")
    if auth:
        try:
            return auth.log_out(url_for("auth_local.login", _external=True))
        except Exception:
            pass
    return redirect(url_for("auth_local.login"))
