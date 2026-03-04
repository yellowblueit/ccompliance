"""
Configuration loader: reads config.json with environment variable overrides.
Optionally loads secrets from Azure Key Vault.
"""
import json
import logging
import os
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.json"

# Keys whose values are sensitive secrets (candidates for Key Vault).
# NOTE: graph_client_secret is intentionally excluded — it's the bootstrap
# credential used to authenticate to Key Vault itself, so it must remain in
# config.json even when Key Vault mode is active.
SECRET_KEYS = {
    "anthropic_compliance_access_key",
    "storage_connection_string",
}

# Mapping: config key -> Key Vault secret name config key
SECRET_NAME_MAP = {
    "anthropic_compliance_access_key": "keyvault_secret_anthropic_key",
    "graph_client_secret": "keyvault_secret_graph_secret",
    "storage_connection_string": "keyvault_secret_storage_conn",
}

DEFAULT_CONFIG = {
    "anthropic_compliance_access_key": "",
    "anthropic_base_url": "https://api.anthropic.com",
    "graph_tenant_id": "",
    "graph_client_id": "",
    "graph_client_secret": "",
    "compliance_mailbox": "",
    "compliance_folder_name": "Anthropic Claude Archive",
    "compliance_folder_hidden": True,
    "storage_connection_string": "",
    "activity_batch_size": 500,
    "chat_batch_size": 100,
    "ingest_chat_content": True,
    "sync_schedule_cron": "*/15 * * * *",
    "sync_enabled": False,
    "display_timezone": "UTC",
    # Branding & Theme
    "brand_app_name": "CCompliance",
    "brand_sidebar_color": "#1a1a2e",
    "brand_accent_color": "#6b21a8",
    "brand_logo_filename": "",
    # Per-user archive selection
    "archive_all_users": False,
    "archive_user_ids": [],
    # Credential storage
    "credential_storage": "local",       # "local" or "keyvault"
    "keyvault_url": "",                   # e.g. https://myvault.vault.azure.net/
    "keyvault_secret_anthropic_key": "anthropic-compliance-access-key",
    "keyvault_secret_graph_secret": "graph-client-secret",
    "keyvault_secret_storage_conn": "storage-connection-string",
    # Entra ID auth (always from env vars for security)
    "entra_client_id": "",
    "entra_client_secret": "",
    "entra_tenant_id": "",
    "entra_redirect_uri": "http://localhost:5000/getAToken",
    "flask_secret_key": "",
    "graph_admin_consent_at": "",
}

ENV_MAP = {
    "anthropic_compliance_access_key": "ANTHROPIC_COMPLIANCE_ACCESS_KEY",
    "anthropic_base_url": "ANTHROPIC_BASE_URL",
    "graph_tenant_id": "GRAPH_TENANT_ID",
    "graph_client_id": "GRAPH_CLIENT_ID",
    "graph_client_secret": "GRAPH_CLIENT_SECRET",
    "compliance_mailbox": "COMPLIANCE_MAILBOX",
    "compliance_folder_name": "COMPLIANCE_FOLDER_NAME",
    "compliance_folder_hidden": "COMPLIANCE_FOLDER_HIDDEN",
    "storage_connection_string": "AzureWebJobsStorage",
    "activity_batch_size": "ACTIVITY_BATCH_SIZE",
    "chat_batch_size": "CHAT_BATCH_SIZE",
    "ingest_chat_content": "INGEST_CHAT_CONTENT",
    "sync_schedule_cron": "SYNC_SCHEDULE_CRON",
    "sync_enabled": "SYNC_ENABLED",
    "brand_app_name": "BRAND_APP_NAME",
    "brand_sidebar_color": "BRAND_SIDEBAR_COLOR",
    "brand_accent_color": "BRAND_ACCENT_COLOR",
    "credential_storage": "CREDENTIAL_STORAGE",
    "keyvault_url": "KEYVAULT_URL",
    "entra_client_id": "ENTRA_CLIENT_ID",
    "entra_client_secret": "ENTRA_CLIENT_SECRET",
    "entra_tenant_id": "ENTRA_TENANT_ID",
    "entra_redirect_uri": "ENTRA_REDIRECT_URI",
    "flask_secret_key": "FLASK_SECRET_KEY",
}

logger = logging.getLogger(__name__)

# ── Cloud persistence (Azure Table Storage) ───────────────────────────
# Non-secret config keys persisted to AppSettingsStore so settings survive
# redeployment even if config.json is wiped.  Stored with a "cfg_" prefix
# to avoid colliding with auth settings already in the same table.

_cloud_store = None   # set once by app.py after AppSettingsStore init


def set_cloud_store(store):
    """Register the AppSettingsStore for cross-deployment config persistence."""
    global _cloud_store
    _cloud_store = store


_CLOUD_PERSIST_KEYS = {
    "anthropic_base_url",
    "graph_tenant_id",
    "graph_client_id",
    "compliance_mailbox",
    "compliance_folder_name",
    "compliance_folder_hidden",
    "activity_batch_size",
    "chat_batch_size",
    "ingest_chat_content",
    "sync_schedule_cron",
    "sync_enabled",
    "display_timezone",
    "brand_app_name",
    "brand_sidebar_color",
    "brand_accent_color",
    "brand_logo_filename",
    "archive_all_users",
    "archive_user_ids",
    "credential_storage",
    "keyvault_url",
    "keyvault_secret_anthropic_key",
    "keyvault_secret_graph_secret",
    "keyvault_secret_storage_conn",
    "graph_admin_consent_at",
}


def _persist_to_cloud(updates):
    """Write eligible config keys to the cloud store."""
    if not _cloud_store:
        return
    for key, value in updates.items():
        if key not in _CLOUD_PERSIST_KEYS:
            continue
        try:
            if isinstance(value, (list, dict)):
                _cloud_store.set_setting(f"cfg_{key}", json.dumps(value))
            elif isinstance(value, bool):
                _cloud_store.set_setting(f"cfg_{key}", "true" if value else "false")
            else:
                _cloud_store.set_setting(f"cfg_{key}", str(value))
        except Exception as e:
            logger.warning("Could not persist '%s' to cloud: %s", key, e)


def load_config_from_cloud(store=None):
    """Load persisted config from AppSettingsStore.  Returns a dict."""
    s = store or _cloud_store
    if not s:
        return {}
    try:
        all_settings = s.get_all_settings()
    except Exception as e:
        logger.warning("Could not read cloud config: %s", e)
        return {}

    result = {}
    for raw_key, raw_value in all_settings.items():
        if not raw_key.startswith("cfg_"):
            continue
        key = raw_key[4:]  # strip "cfg_" prefix
        if key not in DEFAULT_CONFIG:
            continue
        default = DEFAULT_CONFIG[key]
        try:
            if isinstance(default, bool):
                result[key] = raw_value.lower() in ("true", "1", "yes")
            elif isinstance(default, int):
                result[key] = int(raw_value)
            elif isinstance(default, list):
                result[key] = json.loads(raw_value)
            else:
                result[key] = raw_value
        except (ValueError, TypeError):
            result[key] = raw_value
    return result


def _get_keyvault_client(vault_url, config=None):
    """Create a Key Vault SecretClient.

    On Azure App Service, uses the system-assigned Managed Identity (fast, no
    credentials needed).  Locally, falls back to Entra/Graph client credentials
    or DefaultAzureCredential.
    """
    from azure.keyvault.secrets import SecretClient

    # On Azure App Service the Managed Identity is the simplest and most
    # reliable way to reach Key Vault (the ARM template grants it access).
    if os.environ.get("WEBSITE_SITE_NAME"):
        from azure.identity import ManagedIdentityCredential
        credential = ManagedIdentityCredential()
        return SecretClient(vault_url=vault_url, credential=credential)

    # Local dev: try Entra ID / Graph client credentials, then DefaultAzureCredential
    cfg = config or {}
    tenant = (cfg.get("entra_tenant_id")
              or os.environ.get("ENTRA_TENANT_ID", "")
              or cfg.get("graph_tenant_id", ""))
    client_id = (cfg.get("entra_client_id")
                 or os.environ.get("ENTRA_CLIENT_ID", "")
                 or cfg.get("graph_client_id", ""))
    client_secret = (cfg.get("entra_client_secret")
                     or os.environ.get("ENTRA_CLIENT_SECRET", "")
                     or cfg.get("graph_client_secret", ""))

    if tenant and client_id and client_secret:
        from azure.identity import ClientSecretCredential
        credential = ClientSecretCredential(tenant, client_id, client_secret)
    else:
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()

    return SecretClient(vault_url=vault_url, credential=credential)


def _load_keyvault_secrets(config):
    """If keyvault mode is active, fetch secrets and overlay onto config.

    Called at startup (from app.py) and from the Settings UI when the user
    saves or tests Key Vault configuration.
    """
    if config.get("credential_storage") != "keyvault":
        return
    vault_url = config.get("keyvault_url", "").strip()
    if not vault_url:
        return
    try:
        client = _get_keyvault_client(vault_url, config)
        for config_key, name_key in SECRET_NAME_MAP.items():
            secret_name = config.get(name_key, "")
            if not secret_name:
                continue
            try:
                secret = client.get_secret(secret_name)
                if secret.value:
                    config[config_key] = secret.value
            except Exception as e:
                logger.warning("Key Vault: could not read '%s': %s", secret_name, e)
    except Exception as e:
        logger.error("Key Vault connection failed: %s", e)


def load_config():
    config = dict(DEFAULT_CONFIG)

    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r") as f:
            file_config = json.load(f)
        config.update({k: v for k, v in file_config.items() if k in DEFAULT_CONFIG})

    for key, env_name in ENV_MAP.items():
        env_val = os.environ.get(env_name)
        if env_val is not None:
            if isinstance(DEFAULT_CONFIG[key], bool):
                config[key] = env_val.lower() in ("true", "1", "yes")
            elif isinstance(DEFAULT_CONFIG[key], int):
                try:
                    config[key] = int(env_val)
                except ValueError:
                    pass
            else:
                config[key] = env_val

    return config


# Keys that must never be saved to config.json
_NEVER_SAVE_KEYS = {
    "entra_client_id", "entra_client_secret", "entra_tenant_id",
    "entra_redirect_uri", "flask_secret_key",
}


def save_config(updates: dict):
    file_config = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r") as f:
            file_config = json.load(f)

    # Determine if we should exclude secrets from the file
    # (use the incoming value if present, otherwise check existing config)
    storage_mode = updates.get("credential_storage",
                               file_config.get("credential_storage", "local"))
    exclude_secrets = storage_mode == "keyvault"

    # When Key Vault is active, strip ALL secrets from config.json
    if exclude_secrets:
        for secret_key in SECRET_KEYS:
            file_config.pop(secret_key, None)

    for key, value in updates.items():
        if key not in DEFAULT_CONFIG:
            continue
        if key in _NEVER_SAVE_KEYS:
            continue
        if exclude_secrets and key in SECRET_KEYS:
            continue
        file_config[key] = value

    with open(CONFIG_FILE, "w") as f:
        json.dump(file_config, f, indent=2)

    # Also persist to cloud store (survives redeployment)
    _persist_to_cloud(updates)


def save_to_keyvault(vault_url, secrets, config=None):
    """Write secrets to Azure Key Vault.

    Args:
        vault_url: Key Vault URL
        secrets: dict of {secret_name: secret_value}
        config: optional config dict for Entra credentials
    """
    client = _get_keyvault_client(vault_url, config)
    for name, value in secrets.items():
        if value:  # only write non-empty values
            client.set_secret(name, value)


def get_wizard_status(config=None):
    """Return wizard step completion booleans derived from config values."""
    cfg = config or load_config()
    has_graph = all(cfg.get(k) for k in ("graph_tenant_id", "graph_client_id"))
    kv_active = cfg.get("credential_storage") == "keyvault" and bool(cfg.get("keyvault_url"))
    # In KV mode, graph_client_secret is in KV — step 1 is complete if tenant+client are set
    if not kv_active:
        has_graph = has_graph and bool(cfg.get("graph_client_secret"))
    return {
        "step1_complete": has_graph,
        "step2_complete": bool(cfg.get("graph_admin_consent_at", "")),
        "step3_complete": bool(cfg.get("anthropic_compliance_access_key")) or kv_active,
        "step4_complete": kv_active,
        "credential_storage": cfg.get("credential_storage", "local"),
        "keyvault_url": cfg.get("keyvault_url", ""),
    }


def test_keyvault_connection(vault_url, config=None):
    """Test connectivity to Azure Key Vault. Returns (success, message)."""
    try:
        client = _get_keyvault_client(vault_url, config)
        # List one page of secret properties to verify access
        page = client.list_properties_of_secrets()
        count = 0
        for _ in page:
            count += 1
            if count >= 1:
                break
        return True, f"Connected to Key Vault. Found {count}+ secret(s)."
    except Exception as e:
        return False, str(e)
