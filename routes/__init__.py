"""
Shared helpers for route blueprints.
"""
import logging
from functools import wraps
from flask import session, redirect, url_for, current_app, request, jsonify, flash
from clients.anthropic_client import AnthropicComplianceClient

logger = logging.getLogger(__name__)

# Dev-mode mock user gets super_admin permissions so nothing is blocked
_DEV_PERMISSIONS = [
    "view_dashboard", "view_activities", "view_chats", "view_chat_content",
    "delete_chats", "view_projects", "delete_projects", "delete_files",
    "view_organizations", "manage_settings", "manage_sync", "manage_users", "manage_roles",
]


def _is_dev_mode():
    """True when no auth method is configured (original dev fallback)."""
    auth = current_app.config.get("AUTH")
    cfg = current_app.config.get("APP_CONFIG", {})
    entra_enabled = cfg.get("entra_enabled", False)
    local_enabled = cfg.get("local_auth_enabled", False)

    # Also check AppSettingsStore if storage is configured
    store = current_app.config.get("APP_SETTINGS_STORE")
    if store:
        try:
            entra_enabled = store.get_setting("entra_enabled", "false").lower() == "true"
            local_enabled = store.get_setting("local_auth_enabled", "false").lower() == "true"
        except Exception:
            pass

    return auth is None and not entra_enabled and not local_enabled


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if _is_dev_mode():
            if "user" not in session:
                session["user"] = {
                    "name": "Dev User",
                    "preferred_username": "dev@localhost",
                    "role_id": "super_admin",
                    "role_name": "Super Admin",
                    "permissions": _DEV_PERMISSIONS,
                }
            return f(*args, **kwargs)

        if "user" not in session:
            return redirect(url_for("auth_local.login"))

        # Redirect to setup wizard if first-run setup is not complete
        # (skip for /setup paths and /settings/api/wizard paths to avoid loops)
        path = request.path
        if not path.startswith("/setup") and not path.startswith("/settings/api/wizard"):
            store = current_app.config.get("APP_SETTINGS_STORE")
            if store:
                setup_done = store.get_setting("setup_complete", "false").lower() == "true"
                if not setup_done:
                    return redirect(url_for("setup.index"))

        return f(*args, **kwargs)
    return decorated


def require_permission(perm):
    """Decorator: requires a named permission in session['user']['permissions']."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if _is_dev_mode():
                return f(*args, **kwargs)
            user = session.get("user", {})
            perms = user.get("permissions", [])
            if perm not in perms:
                if request.is_json or request.path.startswith("/scim/"):
                    return jsonify({"error": "Forbidden", "detail": f"Missing permission: {perm}"}), 403
                flash(f"Access denied: you need the '{perm}' permission.", "danger")
                return redirect(url_for("dashboard.index"))
            return f(*args, **kwargs)
        return decorated
    return decorator


def resolve_user_session(user_dict, user_store):
    """
    Given a user dict from UserStore, load role permissions and build the
    full session payload. Returns a dict suitable for session["user"].
    """
    role_id = user_dict.get("role_id", "readonly")
    permissions = []
    role_name = role_id

    if user_store:
        try:
            permissions = user_store.get_permissions_for_role(role_id)
            role = user_store.get_role_by_id(role_id)
            if role:
                role_name = role.get("name", role_id)
        except Exception as e:
            logger.warning("resolve_user_session: could not load role %s: %s", role_id, e)

    return {
        "id": user_dict.get("id", ""),
        "name": user_dict.get("display_name") or user_dict.get("username", "User"),
        "preferred_username": user_dict.get("email") or user_dict.get("username", ""),
        "role_id": role_id,
        "role_name": role_name,
        "permissions": permissions,
        "auth_type": user_dict.get("auth_type", "local"),
    }


def get_user_store():
    """Returns the UserStore instance from app context, or None if not configured."""
    return current_app.config.get("USER_STORE")


def get_app_settings_store():
    """Returns the AppSettingsStore instance from app context, or None."""
    return current_app.config.get("APP_SETTINGS_STORE")


def get_anthropic_client():
    config = current_app.config["APP_CONFIG"]
    key = config.get("anthropic_compliance_access_key")
    if not key:
        return None
    return AnthropicComplianceClient(
        key, config.get("anthropic_base_url", "https://api.anthropic.com"))


def get_graph_client():
    """Return a GraphClient if Microsoft Graph credentials are configured, else None."""
    from clients.graph_client import GraphClient
    config = current_app.config["APP_CONFIG"]
    tenant = config.get("graph_tenant_id", "")
    client_id = config.get("graph_client_id", "")
    secret = config.get("graph_client_secret", "")
    if not (tenant and client_id and secret):
        return None
    return GraphClient(tenant, client_id, secret)
