"""
Flask application: CCompliance API Explorer & Sync
"""
import os
import ssl
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ssl._create_default_https_context = ssl._create_unverified_context

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, redirect, url_for, session
from config import load_config
from auth import init_auth


def _seed_admin_user(app, user_store):
    """Create an initial Super Admin user from ADMIN_USERNAME / ADMIN_PASSWORD
    environment variables if no users exist yet. ARM template deployments set
    these as App Settings so the admin account is ready on first launch."""
    admin_user = os.environ.get("ADMIN_USERNAME", "").strip()
    admin_pass = os.environ.get("ADMIN_PASSWORD", "").strip()
    if not admin_user or not admin_pass:
        return

    existing_users = user_store.list_users()
    if existing_users:
        return  # Users already exist, skip seeding

    from werkzeug.security import generate_password_hash
    user_store.upsert_user({
        "username": admin_user,
        "email": admin_user,
        "display_name": "Administrator",
        "password_hash": generate_password_hash(admin_pass),
        "role_id": "super_admin",
        "auth_type": "local",
        "is_active": True,
    })
    app.logger.info("Bootstrap Super Admin user created: %s", admin_user)

    # Enable local authentication so the admin can actually log in
    settings_store = app.config.get("APP_SETTINGS_STORE")
    if settings_store:
        try:
            settings_store.set_setting("local_auth_enabled", "true")
            app.logger.info("Local authentication enabled (bootstrap).")
        except Exception as e:
            app.logger.warning("Could not enable local auth in settings store: %s", e)


def create_app():
    app = Flask(__name__)

    app_config = load_config()
    app.secret_key = app_config["flask_secret_key"] or os.urandom(32).hex()
    app.config["APP_CONFIG"] = app_config
    app.config["SESSION_TYPE"] = "filesystem"

    logging.basicConfig(level=logging.INFO)
    app.logger.setLevel(logging.INFO)

    # ── Optional Azure Table Storage data stores ─────────────────
    storage_conn = app_config.get("storage_connection_string", "")
    if storage_conn:
        try:
            from clients.user_store import UserStore
            from clients.app_settings_store import AppSettingsStore
            user_store = UserStore(storage_conn)
            app_settings_store = AppSettingsStore(storage_conn)
            app.config["USER_STORE"] = user_store
            app.config["APP_SETTINGS_STORE"] = app_settings_store
            app.logger.info("UserStore and AppSettingsStore initialised.")

            # Bootstrap admin: create Super Admin from env vars on first deploy
            _seed_admin_user(app, user_store)
        except Exception as e:
            app.logger.warning("Could not init Table Storage stores: %s", e)
            app.config["USER_STORE"] = None
            app.config["APP_SETTINGS_STORE"] = None
    else:
        app.config["USER_STORE"] = None
        app.config["APP_SETTINGS_STORE"] = None

    auth = init_auth(app)
    app.config["AUTH"] = auth

    # ── Jinja2 timezone filter ────────────────────────────────────
    @app.template_filter("format_dt")
    def format_dt_filter(value, fmt="%Y-%m-%d %H:%M:%S"):
        """Convert an ISO UTC timestamp string to the configured display timezone."""
        if not value:
            return ""
        tz_name = app.config.get("APP_CONFIG", {}).get("display_timezone", "UTC")
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
        try:
            s = str(value)
            s = s.replace("Z", "+00:00")
            if "+" not in s[10:] and "-" not in s[10:]:
                dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
            else:
                dt = datetime.fromisoformat(s)
            return dt.astimezone(tz).strftime(fmt)
        except Exception:
            return str(value)[:19]

    @app.template_filter("tz_abbr")
    def tz_abbr_filter(tz_name):
        """Return the current abbreviation for a timezone name."""
        try:
            tz = ZoneInfo(tz_name)
            return datetime.now(tz).strftime("%Z")
        except Exception:
            return tz_name

    @app.context_processor
    def inject_globals():
        """Make display timezone, branding, and user permissions available in all templates."""
        cfg = app.config.get("APP_CONFIG", {})
        tz_name = cfg.get("display_timezone", "UTC")
        try:
            tz = ZoneInfo(tz_name)
            tz_abbr = datetime.now(tz).strftime("%Z")
        except Exception:
            tz_abbr = tz_name

        user = session.get("user", {})
        return {
            "display_timezone": tz_name,
            "tz_abbr": tz_abbr,
            "brand": {
                "app_name": cfg.get("brand_app_name", "CCompliance"),
                "sidebar_color": cfg.get("brand_sidebar_color", "#1a1a2e"),
                "accent_color": cfg.get("brand_accent_color", "#6b21a8"),
                "logo_filename": cfg.get("brand_logo_filename", ""),
            },
            "user_permissions": set(user.get("permissions", [])),
            "current_user": user,
        }

    # ── Blueprints ────────────────────────────────────────────────
    from routes.auth_local import auth_local_bp
    from routes.dashboard import dashboard_bp
    from routes.settings import settings_bp
    from routes.activities import activities_bp
    from routes.organizations import organizations_bp
    from routes.chats import chats_bp
    from routes.projects import projects_bp
    from routes.sync_control import sync_bp
    from routes.users import users_bp
    from routes.roles import roles_bp
    from routes.scim import scim_bp

    app.register_blueprint(auth_local_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(settings_bp, url_prefix="/settings")
    app.register_blueprint(activities_bp, url_prefix="/activities")
    app.register_blueprint(organizations_bp, url_prefix="/organizations")
    app.register_blueprint(chats_bp, url_prefix="/chats")
    app.register_blueprint(projects_bp, url_prefix="/projects")
    app.register_blueprint(sync_bp, url_prefix="/sync")
    app.register_blueprint(users_bp, url_prefix="/settings/users")
    app.register_blueprint(roles_bp, url_prefix="/settings/roles")
    app.register_blueprint(scim_bp, url_prefix="/scim/v2")

    @app.route("/")
    def index():
        return redirect(url_for("dashboard.index"))

    if app_config.get("sync_enabled") and app_config.get("anthropic_compliance_access_key"):
        try:
            from services.scheduler_service import init_scheduler
            init_scheduler(app)
        except Exception as e:
            app.logger.error(f"Scheduler init failed: {e}")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
