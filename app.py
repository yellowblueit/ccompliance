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
from config import load_config, _load_keyvault_secrets, set_cloud_store, \
    load_config_from_cloud, _persist_to_cloud, _CLOUD_PERSIST_KEYS, ENV_MAP
from auth import init_auth


def _sync_logo(store, app_config, log):
    """Restore logo from cloud if lost, or seed cloud from disk on first run."""
    logo = app_config.get("brand_logo_filename", "")
    if not logo:
        return
    from pathlib import Path
    import base64
    logo_path = Path(__file__).parent / "static" / "uploads" / logo
    logo_b64 = store.get_setting("cfg_logo_data")

    if logo_path.exists() and not logo_b64:
        # First run: seed logo to cloud store
        try:
            data = logo_path.read_bytes()
            if len(data) < 48_000:
                store.set_setting("cfg_logo_data", base64.b64encode(data).decode())
                log.info("Seeded logo '%s' to cloud store.", logo)
        except Exception as e:
            log.warning("Could not seed logo to cloud store: %s", e)
    elif not logo_path.exists() and logo_b64:
        # Redeployment: restore logo from cloud
        try:
            logo_path.parent.mkdir(parents=True, exist_ok=True)
            logo_path.write_bytes(base64.b64decode(logo_b64))
            log.info("Restored logo '%s' from cloud store.", logo)
        except Exception as e:
            log.warning("Could not restore logo from cloud store: %s", e)


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

    # If Key Vault mode is active, fetch secrets before anything else
    # (storage_connection_string, anthropic key, etc. may live in KV)
    if app_config.get("credential_storage") == "keyvault" and app_config.get("keyvault_url"):
        try:
            _load_keyvault_secrets(app_config)
        except Exception as e:
            logging.getLogger(__name__).warning("Key Vault secret load at startup failed: %s", e)

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

            # Register cloud store for cross-deployment config persistence
            set_cloud_store(app_settings_store)

            # Overlay cloud-persisted config (restores settings after redeployment)
            cloud_cfg = load_config_from_cloud(app_settings_store)
            if cloud_cfg:
                for key, value in cloud_cfg.items():
                    env_name = ENV_MAP.get(key)
                    if env_name and os.environ.get(env_name) is not None:
                        continue   # env var takes priority
                    app_config[key] = value
            else:
                # First run: seed cloud store from current config so existing
                # settings survive future redeployments
                _persist_to_cloud({k: v for k, v in app_config.items()
                                   if k in _CLOUD_PERSIST_KEYS and v})

            # Restore logo file if it was lost but is stored in the cloud,
            # or seed the logo to cloud on first run
            _sync_logo(app_settings_store, app_config, app.logger)

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
    from routes.setup import setup_bp

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
    app.register_blueprint(setup_bp, url_prefix="/setup")

    @app.route("/")
    def index():
        # Redirect to setup wizard if first-run setup is not complete
        store = app.config.get("APP_SETTINGS_STORE")
        if store:
            setup_done = store.get_setting("setup_complete", "false").lower() == "true"
            if not setup_done:
                return redirect(url_for("setup.index"))
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
