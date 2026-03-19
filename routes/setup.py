"""
First-run setup wizard — guides a new deployment through initial configuration.
Shown automatically when setup_complete is not set in AppSettingsStore.
"""
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode

from flask import Blueprint, render_template, request, redirect, url_for, \
    session, current_app, jsonify
from config import load_config, load_config_with_secrets, save_config
from routes import login_required, require_permission

setup_bp = Blueprint("setup", __name__)


def _is_setup_complete():
    """Check if first-run setup has been completed."""
    store = current_app.config.get("APP_SETTINGS_STORE")
    if not store:
        return False
    return store.get_setting("setup_complete", "false").lower() == "true"


@setup_bp.route("/")
@login_required
def index():
    """Render the setup wizard, or redirect to dashboard if already complete."""
    if _is_setup_complete():
        return redirect(url_for("dashboard.index"))

    config = load_config()
    # Merge Entra creds from AppSettingsStore for pre-fill
    store = current_app.config.get("APP_SETTINGS_STORE")
    auth_settings = {}
    if store:
        try:
            auth_settings = store.get_all_settings()
        except Exception:
            pass

    return render_template(
        "setup_wizard.html",
        config=config,
        auth_settings=auth_settings,
        consent_callback_url=url_for("setup.admin_consent_callback", _external=True),
        entra_redirect_uri=request.host_url.rstrip("/") + "/getAToken",
    )


@setup_bp.route("/api/save-auth", methods=["POST"])
@login_required
@require_permission("manage_settings")
def save_auth():
    """Save authentication choice from the setup wizard."""
    data = request.get_json(silent=True) or {}
    auth_choice = data.get("auth_choice", "local")  # "entra", "local", or "both"

    store = current_app.config.get("APP_SETTINGS_STORE")
    if not store:
        return jsonify({"success": False, "message": "Storage not configured."}), 503

    entra_enabled = auth_choice in ("entra", "both")
    local_enabled = auth_choice in ("local", "both")

    auth_updates = {
        "entra_enabled": str(entra_enabled).lower(),
        "local_auth_enabled": str(local_enabled).lower(),
    }

    if entra_enabled:
        for key in ("entra_tenant_id", "entra_client_id", "entra_client_secret", "entra_redirect_uri"):
            val = data.get(key, "").strip()
            if val:
                auth_updates[key] = val

    for key, value in auth_updates.items():
        store.set_setting(key, value)

    # Update in-memory config
    current_app.config["APP_CONFIG"]["entra_enabled"] = entra_enabled
    current_app.config["APP_CONFIG"]["local_auth_enabled"] = local_enabled

    return jsonify({"success": True, "message": "Authentication settings saved."})


@setup_bp.route("/api/complete", methods=["POST"])
@login_required
@require_permission("manage_settings")
def complete():
    """Mark first-run setup as complete."""
    store = current_app.config.get("APP_SETTINGS_STORE")
    if not store:
        return jsonify({"success": False, "message": "Storage not configured."}), 503

    store.set_setting("setup_complete", "true")
    return jsonify({"success": True, "message": "Setup complete."})


@setup_bp.route("/admin-consent", methods=["POST"])
@login_required
@require_permission("manage_settings")
def admin_consent():
    """Initiate admin consent flow, returning the redirect URL as JSON."""
    config = load_config()
    tenant_id = config.get("graph_tenant_id", "").strip()
    client_id = config.get("graph_client_id", "").strip()
    if not tenant_id or not client_id:
        return jsonify({"success": False, "message": "Save Graph credentials first (Step 1)."}), 400

    state = secrets.token_urlsafe(32)
    session["wizard_consent_state"] = state

    callback_url = url_for("setup.admin_consent_callback", _external=True)
    params = urlencode({
        "client_id": client_id,
        "redirect_uri": callback_url,
        "state": state,
    })
    consent_url = f"https://login.microsoftonline.com/{tenant_id}/adminconsent?{params}"
    return jsonify({"success": True, "redirect_url": consent_url})


@setup_bp.route("/admin-consent/callback")
@login_required
def admin_consent_callback():
    """Handle the redirect back from Microsoft's admin consent page."""
    state = request.args.get("state", "")
    expected = session.pop("wizard_consent_state", None)
    if not expected or state != expected:
        return redirect(url_for("setup.index") + "?step=4&consent_error=1")

    error = request.args.get("error")
    if error:
        return redirect(url_for("setup.index") + "?step=4&consent_error=1")

    # Success — save timestamp
    now = datetime.now(timezone.utc).isoformat()
    save_config({"graph_admin_consent_at": now})
    current_app.config["APP_CONFIG"] = load_config_with_secrets()
    return redirect(url_for("setup.index") + "?step=4&consent_ok=1")
