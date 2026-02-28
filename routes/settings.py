import secrets
from pathlib import Path
from flask import Blueprint, render_template, request, flash, redirect, url_for, \
    session, current_app, send_file, jsonify
from werkzeug.utils import secure_filename
from config import load_config, save_config, test_keyvault_connection, \
    CONFIG_FILE
from routes import login_required, require_permission

UPLOAD_DIR = Path(__file__).parent.parent / "static" / "uploads"
ALLOWED_LOGO_EXT = {"png", "jpg", "jpeg", "svg", "gif", "webp", "ico"}

settings_bp = Blueprint("settings", __name__)


def _get_auth_settings():
    """Load auth settings from AppSettingsStore, returning a dict."""
    store = current_app.config.get("APP_SETTINGS_STORE")
    if not store:
        return {}
    try:
        return store.get_all_settings()
    except Exception:
        return {}


def _save_auth_settings(updates: dict):
    """Save a dict of auth settings to AppSettingsStore."""
    store = current_app.config.get("APP_SETTINGS_STORE")
    if not store:
        return
    for key, value in updates.items():
        store.set_setting(key, value)


@settings_bp.route("/")
@login_required
def index():
    tab = request.args.get("tab", "general")
    config = load_config()
    auth_settings = _get_auth_settings()
    return render_template(
        "settings_tabbed.html",
        config=config,
        auth_settings=auth_settings,
        user=session.get("user", {}),
        active_tab=tab,
    )


@settings_bp.route("/save", methods=["POST"])
@login_required
@require_permission("manage_settings")
def save():
    tab = request.form.get("_tab", "general")
    cred_storage = request.form.get("credential_storage", "local").strip()

    # Map old tab values to new tab names for redirects
    TAB_REDIRECT = {"anthropic": "api_setup", "graph": "api_setup", "security": "api_setup"}
    redirect_tab = TAB_REDIRECT.get(tab, tab)

    # Build updates dict based on which tab is being saved
    updates = {}

    if tab == "general":
        updates = {
            "brand_app_name": request.form.get("brand_app_name", "Claude Compliance").strip(),
            "brand_sidebar_color": request.form.get("brand_sidebar_color", "#1a1a2e").strip(),
            "brand_accent_color": request.form.get("brand_accent_color", "#6b21a8").strip(),
            "display_timezone": request.form.get("display_timezone", "UTC").strip(),
        }
        # Handle logo upload
        logo = request.files.get("brand_logo")
        if logo and logo.filename:
            fname = secure_filename(logo.filename)
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else "png"
            if ext in ALLOWED_LOGO_EXT:
                UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                old_logo = load_config().get("brand_logo_filename", "")
                if old_logo:
                    old_path = UPLOAD_DIR / old_logo
                    if old_path.exists():
                        old_path.unlink()
                saved_name = f"logo.{ext}"
                logo.save(str(UPLOAD_DIR / saved_name))
                updates["brand_logo_filename"] = saved_name

    elif tab == "anthropic":
        updates = {
            "anthropic_compliance_access_key": request.form.get("anthropic_compliance_access_key", "").strip(),
            "anthropic_base_url": request.form.get("anthropic_base_url", "https://api.anthropic.com").strip(),
        }

    elif tab == "graph":
        updates = {
            "graph_tenant_id": request.form.get("graph_tenant_id", "").strip(),
            "graph_client_id": request.form.get("graph_client_id", "").strip(),
            "graph_client_secret": request.form.get("graph_client_secret", "").strip(),
        }

    elif tab == "sync":
        updates = {
            "compliance_mailbox": request.form.get("compliance_mailbox", "").strip(),
            "compliance_folder_name": request.form.get("compliance_folder_name", "Anthropic Claude Archive").strip(),
            "compliance_folder_hidden": request.form.get("compliance_folder_hidden") == "on",
            "storage_connection_string": request.form.get("storage_connection_string", "").strip(),
            "activity_batch_size": int(request.form.get("activity_batch_size", 500)),
            "chat_batch_size": int(request.form.get("chat_batch_size", 100)),
            "ingest_chat_content": request.form.get("ingest_chat_content") == "on",
            "sync_schedule_cron": request.form.get("sync_schedule_cron", "*/15 * * * *").strip(),
            "sync_enabled": request.form.get("sync_enabled") == "on",
        }
        if updates.get("sync_enabled"):
            try:
                from services.scheduler_service import update_schedule
                update_schedule(updates["sync_schedule_cron"], updates.get("display_timezone", "UTC"))
            except Exception:
                pass

    elif tab == "security":
        updates = {"credential_storage": cred_storage}
        if cred_storage == "keyvault":
            updates.update({
                "keyvault_url": request.form.get("keyvault_url", "").strip(),
                "keyvault_secret_anthropic_key": request.form.get("keyvault_secret_anthropic_key", "anthropic-compliance-access-key").strip(),
                "keyvault_secret_graph_secret": request.form.get("keyvault_secret_graph_secret", "graph-client-secret").strip(),
                "keyvault_secret_storage_conn": request.form.get("keyvault_secret_storage_conn", "storage-connection-string").strip(),
            })

    elif tab == "auth":
        # Auth settings go to AppSettingsStore, not config.json
        entra_enabled = request.form.get("entra_enabled") == "on"
        local_enabled = request.form.get("local_auth_enabled") == "on"
        auth_updates = {
            "entra_enabled": str(entra_enabled).lower(),
            "local_auth_enabled": str(local_enabled).lower(),
        }
        if entra_enabled:
            tenant = request.form.get("entra_tenant_id", "").strip()
            client_id = request.form.get("entra_client_id", "").strip()
            client_secret = request.form.get("entra_client_secret", "").strip()
            redirect_uri = request.form.get("entra_redirect_uri", "").strip()
            if tenant:
                auth_updates["entra_tenant_id"] = tenant
            if client_id:
                auth_updates["entra_client_id"] = client_id
            if client_secret:
                auth_updates["entra_client_secret"] = client_secret
            if redirect_uri:
                auth_updates["entra_redirect_uri"] = redirect_uri
        _save_auth_settings(auth_updates)
        # Also update in-memory config so login_required sees it immediately
        current_app.config["APP_CONFIG"]["entra_enabled"] = entra_enabled
        current_app.config["APP_CONFIG"]["local_auth_enabled"] = local_enabled
        flash("Authentication settings saved.", "success")
        return redirect(url_for("settings.index", tab=redirect_tab))

    if updates:
        save_config(updates)
        current_app.config["APP_CONFIG"] = load_config()

    flash("Settings saved.", "success")
    return redirect(url_for("settings.index", tab=redirect_tab))


@settings_bp.route("/test-anthropic", methods=["POST"])
@login_required
def test_anthropic():
    config = load_config()
    try:
        from clients.anthropic_client import AnthropicComplianceClient
        client = AnthropicComplianceClient(
            config["anthropic_compliance_access_key"],
            config["anthropic_base_url"])
        orgs = client.list_organizations()
        count = len(orgs if isinstance(orgs, list) else orgs.get("data", []))
        flash(f"Anthropic API connected. Found {count} organization(s).", "success")
    except Exception as e:
        flash(f"Anthropic API failed: {e}", "danger")
    return redirect(url_for("settings.index", tab="api_setup"))


@settings_bp.route("/test-graph", methods=["POST"])
@login_required
def test_graph():
    config = load_config()
    try:
        from clients.graph_client import GraphClient
        client = GraphClient(
            config["graph_tenant_id"],
            config["graph_client_id"],
            config["graph_client_secret"])
        client._ensure_token()
        flash("Microsoft Graph API connected.", "success")
    except Exception as e:
        flash(f"Graph API failed: {e}", "danger")
    return redirect(url_for("settings.index", tab="api_setup"))


@settings_bp.route("/test-keyvault", methods=["POST"])
@login_required
def test_keyvault():
    config = load_config()
    # Merge Entra creds from AppSettingsStore — load_config() doesn't include
    # them because they're in _NEVER_SAVE_KEYS (never written to config.json).
    auth = _get_auth_settings()
    for k in ("entra_tenant_id", "entra_client_id", "entra_client_secret"):
        if auth.get(k):
            config[k] = auth[k]

    vault_url = config.get("keyvault_url", "").strip()
    if not vault_url:
        flash("Key Vault URL is not configured.", "warning")
        return redirect(url_for("settings.index", tab="api_setup"))

    # Check both credential paths: Entra creds OR Graph creds (same app reg)
    has_entra = all(config.get(k) for k in ("entra_tenant_id", "entra_client_id", "entra_client_secret"))
    has_graph = all(config.get(k) for k in ("graph_tenant_id", "graph_client_id", "graph_client_secret"))
    cred_source = "Entra ID" if has_entra else ("Graph API" if has_graph else None)

    current_app.logger.info(
        "Key Vault test — cred_source=%s, entra=%s, graph=%s",
        cred_source, has_entra, has_graph,
    )

    if not cred_source:
        flash(
            "Key Vault test will use DefaultAzureCredential (no app credentials found). "
            "Configure the Microsoft Graph API card on the API Setup tab first.",
            "warning"
        )

    ok, msg = test_keyvault_connection(vault_url, config)
    if ok:
        flash(f"Key Vault: {msg}", "success")
    else:
        flash(f"Key Vault connection failed: {msg}", "danger")
    return redirect(url_for("settings.index", tab="api_setup"))


@settings_bp.route("/test-entra", methods=["POST"])
@login_required
def test_entra():
    auth_settings = _get_auth_settings()
    tenant = auth_settings.get("entra_tenant_id", "").strip()
    client_id = auth_settings.get("entra_client_id", "").strip()
    client_secret = auth_settings.get("entra_client_secret", "").strip()
    if not all([tenant, client_id, client_secret]):
        flash("Entra ID credentials are not fully configured.", "warning")
        return redirect(url_for("settings.index", tab="auth"))
    try:
        import msal
        app = msal.ConfidentialClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant}",
            client_credential=client_secret,
        )
        result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        if "access_token" in result:
            flash("Entra ID connection successful.", "success")
        else:
            flash(f"Entra ID auth failed: {result.get('error_description', result.get('error', 'Unknown error'))}", "danger")
    except Exception as e:
        flash(f"Entra ID test failed: {e}", "danger")
    return redirect(url_for("settings.index", tab="auth"))


@settings_bp.route("/generate-scim-token", methods=["POST"])
@login_required
@require_permission("manage_settings")
def generate_scim_token():
    store = current_app.config.get("APP_SETTINGS_STORE")
    if not store:
        return jsonify({"error": "App settings store not configured (Azure Storage required)"}), 503
    token = secrets.token_urlsafe(40)
    store.set_setting("scim_bearer_token", token)
    return jsonify({"token": token})


@settings_bp.route("/api/users")
@login_required
def api_users():
    """Fetch all Claude org users enriched with Graph API mailbox status."""
    config = load_config()
    archive_user_ids = config.get("archive_user_ids", [])

    anthropic_key = config.get("anthropic_compliance_access_key")
    if not anthropic_key:
        return jsonify({"error": "Anthropic API not configured", "users": []})

    from clients.anthropic_client import AnthropicComplianceClient
    ac = AnthropicComplianceClient(anthropic_key, config.get("anthropic_base_url", "https://api.anthropic.com"))

    try:
        result = ac.list_organizations()
        orgs = result if isinstance(result, list) else result.get("data", [])
    except Exception as e:
        return jsonify({"error": f"Failed to list organizations: {e}", "users": []})

    users = []
    user_id_set = set()
    for org in orgs:
        org_uuid = org.get("uuid") or org.get("id") or ""
        org_name = org.get("name", "")
        if not org_uuid:
            continue
        try:
            result = ac.list_organization_users(org_uuid)
            data = result.get("data", []) if isinstance(result, dict) else (result or [])
            for u in data:
                uid = u.get("user_id") or u.get("id") or ""
                if uid and uid not in user_id_set:
                    user_id_set.add(uid)
                    raw_status = u.get("status") or u.get("membership_status") or "active"
                    users.append({
                        "id": uid,
                        "email": u.get("email") or u.get("email_address") or "",
                        "name": u.get("name") or "",
                        "role": u.get("role") or "",
                        "status": raw_status,
                        "org_name": org_name,
                        "org_id": org_uuid,
                        "selected": uid in archive_user_ids,
                    })
        except Exception:
            continue

    graph_status = {}
    graph_configured = all([config.get("graph_tenant_id"), config.get("graph_client_id"), config.get("graph_client_secret")])
    if graph_configured:
        try:
            from clients.graph_client import GraphClient
            gc = GraphClient(config["graph_tenant_id"], config["graph_client_id"], config["graph_client_secret"])
            emails = [u["email"] for u in users if u["email"]]
            graph_status = gc.check_users_mailbox_status(emails)
        except Exception:
            pass

    for u in users:
        email_lower = (u["email"] or "").lower()
        gs = graph_status.get(email_lower, {})
        u["has_mailbox"] = gs.get("exists", False) if graph_status else None
        u["account_enabled"] = gs.get("enabled", None) if graph_status else None
        u["graph_display_name"] = gs.get("display_name", "") if graph_status else ""

    users.sort(key=lambda u: (not u["selected"], (u["email"] or u["id"]).lower()))

    return jsonify({
        "users": users,
        "graph_configured": graph_configured,
        "total": len(users),
        "selected_count": sum(1 for u in users if u["selected"]),
    })


@settings_bp.route("/save-archive-users", methods=["POST"])
@login_required
def save_archive_users():
    data = request.get_json(silent=True) or {}
    user_ids = data.get("user_ids", [])
    archive_all = bool(data.get("archive_all", False))
    if not isinstance(user_ids, list):
        return jsonify({"error": "user_ids must be a list"}), 400
    save_config({"archive_user_ids": user_ids, "archive_all_users": archive_all})
    current_app.config["APP_CONFIG"] = load_config()
    return jsonify({"status": "ok", "count": len(user_ids), "archive_all": archive_all})


@settings_bp.route("/remove-logo", methods=["POST"])
@login_required
def remove_logo():
    config = load_config()
    logo_file = config.get("brand_logo_filename", "")
    if logo_file:
        logo_path = UPLOAD_DIR / logo_file
        if logo_path.exists():
            logo_path.unlink()
    save_config({"brand_logo_filename": ""})
    current_app.config["APP_CONFIG"] = load_config()
    flash("Logo removed.", "success")
    return redirect(url_for("settings.index", tab="general"))


@settings_bp.route("/download-config")
@login_required
def download_config():
    if CONFIG_FILE.exists():
        return send_file(str(CONFIG_FILE), as_attachment=True,
                         download_name="config.json", mimetype="application/json")
    flash("No config.json file exists yet.", "warning")
    return redirect(url_for("settings.index"))
