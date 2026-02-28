"""
Microsoft Entra ID authentication via identity.flask.Auth.
Includes JWT role extraction and user auto-provisioning.
"""
import logging
from functools import wraps
from flask import session, redirect, url_for

logger = logging.getLogger(__name__)


def init_auth(app):
    config = app.config["APP_CONFIG"]

    # Check AppSettingsStore for entra_enabled override
    store = app.config.get("APP_SETTINGS_STORE")
    entra_enabled = False
    tenant_id = ""
    client_id = ""
    client_secret = ""
    redirect_uri = ""

    if store:
        try:
            entra_enabled = store.get_setting("entra_enabled", "false").lower() == "true"
            tenant_id = store.get_setting("entra_tenant_id", "") or config.get("entra_tenant_id", "")
            client_id = store.get_setting("entra_client_id", "") or config.get("entra_client_id", "")
            client_secret = store.get_setting("entra_client_secret", "") or config.get("entra_client_secret", "")
            redirect_uri = store.get_setting("entra_redirect_uri", "") or config.get("entra_redirect_uri", "http://localhost:5000/getAToken")
        except Exception:
            pass
    else:
        tenant_id = config.get("entra_tenant_id", "")
        client_id = config.get("entra_client_id", "")
        client_secret = config.get("entra_client_secret", "")
        redirect_uri = config.get("entra_redirect_uri", "http://localhost:5000/getAToken")
        entra_enabled = bool(tenant_id and client_id)

    if not entra_enabled or not tenant_id or not client_id:
        app.logger.warning("Entra ID not configured - auth disabled for development")
        return None

    try:
        from identity.flask import Auth
        auth = Auth(
            app,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_id=client_id,
            client_credential=client_secret,
            redirect_uri=redirect_uri,
        )

        # Hook into the post-login flow to extract roles and provision user
        _register_entra_callback(app, auth)
        return auth
    except Exception as e:
        app.logger.error("Failed to init Entra ID auth: %s", e)
        return None


def _register_entra_callback(app, auth):
    """
    Register a route that fires after identity.flask completes the login.
    We override /getAToken to extract JWT claims and resolve roles.
    """
    # identity.flask registers /getAToken itself; we patch in post-processing
    # by wrapping the after_request handler when the redirect is from Entra.
    # The cleanest approach: after the identity library sets session["user"],
    # we immediately resolve the role.
    original_route = None

    @app.after_request
    def _entra_post_login(response):
        """After Entra ID sets session["user"], resolve roles if not already done."""
        user = session.get("user", {})
        if user and "permissions" not in user and user.get("preferred_username"):
            # Entra has populated the session but we haven't resolved roles yet
            _resolve_entra_user_session(app)
        return response


def _resolve_entra_user_session(app):
    """
    Extract roles from the Entra ID session token and map to app roles.
    Called after identity.flask populates session["user"].
    """
    user_data = session.get("user", {})
    if not user_data:
        return

    # Get the raw id_token claims if available
    # identity.flask stores the user's claims dict in session["user"]
    # The "roles" claim contains the App Roles assigned to the user
    roles_claim = user_data.get("roles", [])

    # Also try to decode the id_token for roles if available
    token = user_data.get("id_token", "")
    if token and not roles_claim:
        try:
            import jwt as pyjwt
            claims = pyjwt.decode(token, options={"verify_signature": False})
            roles_claim = claims.get("roles", [])
        except Exception as e:
            logger.warning("JWT decode failed: %s", e)

    # Resolve role: take the first matching App Role from our store
    user_store = app.config.get("USER_STORE")
    role_id = "readonly"
    role_name = "Read Only"
    permissions = []

    if user_store and roles_claim:
        for role_val in roles_claim:
            role = user_store.get_role_by_name(role_val)
            if role:
                role_id = role["id"]
                role_name = role["name"]
                permissions = role.get("permissions", [])
                break

    elif user_store:
        # No roles claim: assign default readonly
        role = user_store.get_role_by_id("readonly")
        if role:
            role_id = role["id"]
            role_name = role["name"]
            permissions = role.get("permissions", [])

    # Auto-provision or update the user in our local store
    if user_store:
        entra_id = user_data.get("oid") or user_data.get("sub", "")
        email = user_data.get("preferred_username", "") or user_data.get("email", "")
        display_name = user_data.get("name", "") or email

        existing = user_store.get_user_by_entra_id(entra_id) if entra_id else None
        user_dict = existing or {
            "auth_type": "entra",
            "entra_id": entra_id,
            "username": email,
            "email": email,
            "display_name": display_name,
        }
        user_dict["role_id"] = role_id
        user_dict["is_active"] = True
        if not existing:
            user_dict["display_name"] = display_name
        user_store.upsert_user(user_dict)

    # Update session with resolved permissions
    session["user"] = {
        "id": user_data.get("oid") or user_data.get("sub", ""),
        "name": user_data.get("name", ""),
        "preferred_username": user_data.get("preferred_username", ""),
        "roles": roles_claim,
        "role_id": role_id,
        "role_name": role_name,
        "permissions": permissions,
        "auth_type": "entra",
        # Preserve identity.flask required fields
        "oid": user_data.get("oid", ""),
    }
    logger.info("Entra login: %s → role: %s", user_data.get("preferred_username"), role_name)
