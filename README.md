# CCompliance

A compliance management dashboard for **Anthropic Claude**, built on Flask and deployed to **Azure App Service**. Provides a full GUI for the Anthropic Compliance API, role-based access control, and optional background sync to **Microsoft Purview** via the Graph API.

---

## Table of Contents

- [Features](#features)
- [Quick Start — Azure Deployment](#quick-start--azure-deployment)
- [Local Development](#local-development)
- [Setup Wizard](#setup-wizard)
- [Architecture](#architecture)
- [Authentication](#authentication)
- [Role-Based Access Control](#role-based-access-control)
- [SCIM 2.0 Provisioning](#scim-20-provisioning)
- [Pages & Functionality](#pages--functionality)
- [Purview Sync](#purview-sync)
- [Azure Key Vault](#azure-key-vault)
- [Configuration Reference](#configuration-reference)
- [Troubleshooting](#troubleshooting)

---

## Features

| Category | Features |
|---|---|
| **Compliance Dashboard** | Connection status, activity statistics with async loading, quick-action links |
| **Activity Feed** | Browse, filter, and inspect all compliance events across 15+ activity categories. Server-Sent Events for progressive streaming. IP geolocation and Entra ID user profile lookup |
| **Chat Explorer** | Search by user, org, project, date. View full conversation threads with styled messages. Download attachments individually or as ZIP. Delete chats with confirmation |
| **Project Browser** | Browse projects, view prompt templates, inspect attachments, view/delete documents |
| **Organizations** | List organizations and drill into user rosters with pagination |
| **Purview Sync** | Background scheduler syncs activities and chats to a Microsoft compliance mailbox as formatted HTML emails with file attachments. Manual trigger with live log viewer |
| **Settings** | Tabbed UI: General/Branding, API Setup Wizard, Authentication, Sync, Archive, Users, Roles |
| **Authentication** | Local username/password, Microsoft Entra ID SSO, or dev-mode auto-login |
| **RBAC** | 13 granular permissions, 4 built-in roles, custom role creation, Entra ID role mapping |
| **SCIM 2.0** | Full provisioning endpoint for automated user and group management from Entra ID |
| **Key Vault** | Store secrets in Azure Key Vault using the App Service's Managed Identity |
| **Branding** | Configurable app name, sidebar color, accent color, and logo upload |

---

## Quick Start — Azure Deployment

### 1. Deploy the ARM template

Click **Deploy to Azure** or deploy [azuredeploy.json](azuredeploy.json) from the Azure Portal:

| Parameter | Description |
|---|---|
| `appName` | Globally unique name for your Web App |
| `skuName` | App Service Plan tier (default: B1 ~$13/month) |
| `adminUsername` | Username for the initial Super Admin account |
| `adminPassword` | Password for the initial Super Admin account |

The template provisions:
- **Storage Account** (Standard_LRS, TLS 1.2, HTTPS-only) — used for user accounts, roles, settings, and sync state
- **App Service Plan** (Linux)
- **Web App** (Python 3.12) with system-assigned **Managed Identity**, Always On, HTTPS-only, FTP disabled

### 2. Deploy your code

Set up **External Git** (or Local Git / ZIP deploy) in the Azure Portal under **Deployment Center**:
1. Go to **Deployment Center** > **Settings**
2. Choose **External Git** and point to your repository
3. Azure will build and deploy automatically (`SCM_DO_BUILD_DURING_DEPLOYMENT` is enabled)

### 3. Log in and run the Setup Wizard

1. Browse to `https://<appName>.azurewebsites.net/login`
2. Sign in with the admin credentials you set during ARM deployment
3. Go to **Settings** > **API Setup** tab
4. Follow the step-by-step wizard to configure Azure App Registration, API permissions, Anthropic API key, and Key Vault

---

## Local Development

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Create your environment file

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```ini
ANTHROPIC_COMPLIANCE_ACCESS_KEY=sk-ant-api01-your-key-here
```

Leave Entra ID and local auth fields empty to run in **dev mode** (auto-login, no authentication required).

### 3. Run the application

```bash
python app.py
```

The app starts at **http://localhost:5000**. In dev mode you're automatically logged in as "Dev User" with full permissions.

---

## Setup Wizard

The **API Setup** tab in Settings provides a guided 5-step wizard:

| Step | What It Does |
|---|---|
| **1. Azure App Registration** | Enter Tenant ID, Client ID, and Client Secret. Includes a collapsible setup guide with links to the Azure Portal. **Test Connection** validates MSAL token acquisition before saving. |
| **2. API Permissions & Admin Consent** | Shows required Graph permissions (User.Read.All, Mail.ReadWrite, Mail.Send). **Grant Admin Consent** button triggers the OAuth admin consent flow. Skippable if your Global Admin handles consent separately. |
| **3. Anthropic Compliance API** | Enter your access key and base URL. **Test Connection** calls `list_organizations()` to verify. |
| **4. Azure Key Vault** | Enter your Key Vault URL and secret names. **Test Connection** verifies Managed Identity access. **Migrate Secrets** writes all credentials to Key Vault and strips them from config.json. |
| **5. Summary** | Checklist of all steps with completion status and next-steps links. |

Each step validates before allowing you to proceed. The wizard auto-opens the first incomplete step on page load.

When Key Vault is active, secret fields show "Stored in Key Vault" badges instead of input fields, and the Graph API client secret field is hidden (the App Service's Managed Identity pulls it from Key Vault directly).

---

## Architecture

```
CCompliance/
├── app.py                          # Flask app factory, blueprint registration, scheduler init
├── config.py                       # Config loader: config.json → env vars → Key Vault
├── auth.py                         # Entra ID authentication setup (MSAL/identity[flask])
├── requirements.txt                # Python dependencies
├── startup.sh                      # Azure App Service startup command
├── gunicorn.conf.py                # Gunicorn config: 1 worker, 600s timeout
├── azuredeploy.json                # ARM template: App Service + Storage Account
├── .env.example                    # Environment variable template
│
├── clients/
│   ├── anthropic_client.py         # Anthropic Compliance API client (14 endpoints)
│   ├── graph_client.py             # Microsoft Graph API (mail, folders, user profiles)
│   ├── user_store.py               # Azure Table Storage: users + roles
│   ├── app_settings_store.py       # Azure Table Storage: runtime settings
│   ├── group_store.py              # Azure Table Storage: SCIM groups
│   └── state_manager.py            # Azure Table Storage: sync cursors
│
├── services/
│   ├── sync_service.py             # Core sync logic (activities + chats → Purview)
│   └── scheduler_service.py        # APScheduler cron wrapper
│
├── routes/
│   ├── __init__.py                 # Shared helpers: login_required, require_permission
│   ├── auth_local.py               # Local username/password login
│   ├── dashboard.py                # Dashboard with async activity stats
│   ├── settings.py                 # Tabbed settings editor + setup wizard API
│   ├── activities.py               # Activity feed with SSE streaming
│   ├── organizations.py            # Organization + user roster browser
│   ├── chats.py                    # Chat search, message viewer, file downloads
│   ├── projects.py                 # Project browser, attachments, documents
│   ├── sync_control.py             # Manual sync trigger + live log viewer
│   ├── users.py                    # User management CRUD
│   ├── roles.py                    # Role management CRUD
│   └── scim.py                     # SCIM 2.0 provider (Users + Groups)
│
├── templates/                      # Jinja2 templates (Bootstrap 5 via CDN)
│   ├── base.html                   # Master layout: sidebar, topbar, branding
│   ├── login.html                  # Login page (local + Entra ID)
│   ├── dashboard.html              # Dashboard
│   ├── settings_tabbed.html        # Tabbed settings (General, API Setup, Auth, Sync, Users, Roles)
│   ├── activities/                 # list.html, detail.html
│   ├── chats/                      # list.html, detail.html
│   ├── projects/                   # list.html, detail.html, document.html
│   ├── organizations/              # list.html, users.html
│   └── sync/                       # control.html
│
└── static/
    ├── css/custom.css              # Custom styling
    ├── js/app.js                   # Delete modals, sync log polling
    └── uploads/                    # Uploaded logo files
```

### Key design decisions

- **Single Gunicorn worker** — APScheduler is not process-safe; one worker prevents duplicate sync runs
- **Config layering** — `config.json` < environment variables < Key Vault. Azure App Settings always win
- **Entra ID secrets never saved to config.json** — always loaded from environment variables
- **Bootstrap 5 via CDN** — no frontend build step required
- **Azure Table Storage** — four tables (`ComplianceUsers`, `ComplianceRoles`, `ComplianceAppSettings`, `ComplianceState`) store all persistent state

### Tech stack

| Layer | Technology |
|---|---|
| Backend | Flask 3.1, Gunicorn 22 |
| Authentication | `identity[flask]` 0.7 (MSAL), Werkzeug password hashing |
| Scheduler | APScheduler 3.10, Flask-APScheduler 1.13 |
| Data storage | Azure Table Storage (`azure-data-tables` 12) |
| Secret management | Azure Key Vault (`azure-keyvault-secrets` 4.8+, `azure-identity` 1.17+) |
| Frontend | Bootstrap 5 (CDN), vanilla JavaScript, Server-Sent Events |
| Runtime | Python 3.10+ (3.12 on Azure) |

---

## Authentication

CCompliance supports three authentication methods, which can be enabled independently:

### Local username/password

- Enabled via **Settings > Authentication > Local Authentication**
- User accounts stored in Azure Table Storage
- Passwords hashed with Werkzeug's `generate_password_hash`
- A Super Admin account is automatically created on first deploy using the `ADMIN_USERNAME` / `ADMIN_PASSWORD` ARM template parameters
- Local auth is automatically enabled when the bootstrap admin is seeded

### Microsoft Entra ID (SSO)

- Enabled via **Settings > Authentication > Entra ID Login**
- Uses OAuth2/OIDC via the `identity[flask]` library
- Restricts login to your Azure AD tenant
- Auto-provisions users on first SSO login with role mapping from Entra ID App Roles
- A collapsible setup guide in the Authentication tab walks through app registration, redirect URIs, and required permissions
- Entra ID credentials are configured via environment variables (never written to config.json)

### Dev mode

- Activates automatically when neither local nor Entra ID auth is configured
- Creates a mock "Dev User" session with full Super Admin permissions
- Intended for local development only

The login page dynamically shows the available sign-in methods. When both local and Entra ID are enabled, users see a **Sign in with Microsoft** button and a local username/password form separated by a divider.

---

## Role-Based Access Control

### Permissions

| Permission | Description |
|---|---|
| `view_dashboard` | View the dashboard page |
| `view_activities` | Browse the activity feed |
| `view_chats` | Search and list chats |
| `view_chat_content` | View full chat message threads |
| `delete_chats` | Delete chats |
| `view_projects` | Browse projects |
| `delete_projects` | Delete projects |
| `delete_files` | Delete project documents and files |
| `view_organizations` | Browse organizations and user rosters |
| `manage_settings` | Access and modify application settings |
| `manage_sync` | Control the Purview sync scheduler |
| `manage_users` | Create, edit, and deactivate user accounts |
| `manage_roles` | Create and modify permission roles |

### Built-in roles

| Role | Permissions |
|---|---|
| **Read Only** | view_dashboard, view_activities, view_chats, view_chat_content, view_projects, view_organizations |
| **Compliance Auditor** | Same as Read Only |
| **SysAdmin** | All view permissions + manage_settings, manage_sync, manage_users (no delete, no chat content) |
| **Super Admin** | All 13 permissions |

Custom roles can be created in **Settings > Roles**. Roles can be mapped to Entra ID App Roles by name for automatic assignment at SSO login.

---

## SCIM 2.0 Provisioning

CCompliance includes a full SCIM 2.0 provider at `/scim/v2/` for automated user and group lifecycle management from Entra ID or other identity providers.

### Endpoints

| Endpoint | Methods |
|---|---|
| `/scim/v2/Users` | GET (list/filter), POST (create) |
| `/scim/v2/Users/{id}` | GET, PUT, PATCH, DELETE |
| `/scim/v2/Groups` | GET (list/filter), POST (create) |
| `/scim/v2/Groups/{id}` | GET, PUT, PATCH, DELETE |
| `/scim/v2/ServiceProviderConfig` | GET |
| `/scim/v2/Schemas` | GET |
| `/scim/v2/ResourceTypes` | GET |

### Setup

1. Generate a SCIM bearer token in **Settings > Authentication > SCIM Provisioning**
2. In Entra ID, add an **Enterprise Application** with SCIM provisioning
3. Set the Tenant URL to `https://<your-app>.azurewebsites.net/scim/v2`
4. Enter the bearer token as the Secret Token
5. Test the connection and start provisioning

SCIM-provisioned users are automatically assigned roles based on their Entra ID group memberships. Deleting a SCIM user sets `is_active=False` to preserve the audit trail.

---

## Pages & Functionality

### Dashboard (`/dashboard`)
Overview page showing connection status for Anthropic API, Graph API, and Purview Sync. Displays activity statistics loaded asynchronously. Quick-action links and a getting-started checklist.

### Activity Feed (`/activities`)
Browse all compliance events with filters for date range, organization, actor, and activity type. Results stream progressively via Server-Sent Events. Click any row for full event details including actor info, additional fields, IP geolocation, and raw JSON. Supports 15+ activity type categories (authentication, chats, files, projects, API keys, org changes, and more).

### Chats (`/chats`)
Search chats by user, organization, project, and date range. Chat detail view shows the full conversation thread with styled user/Claude messages. Download file attachments individually or as a ZIP archive. Delete chats with confirmation (requires typing the chat ID).

### Projects (`/projects`)
Browse projects with filters for organization, user, and date range. Project detail shows metadata, prompt templates, and attachments. View and delete individual documents.

### Organizations (`/organizations`)
List all organizations accessible via your compliance key. Drill into per-org user rosters with pagination.

### Settings (`/settings`)
Tabbed configuration interface:
- **General** — App name, colors, logo upload, timezone
- **API Setup** — Step-by-step setup wizard (see [Setup Wizard](#setup-wizard))
- **Authentication** — Local auth toggle, Entra ID configuration with setup guide, SCIM token management
- **Sync** — Batch sizes, cron schedule, chat content ingestion toggle, sync enable/disable
- **Archive** — Select which users to archive (all or specific user IDs)
- **Users** — User account management (create, edit, deactivate, assign roles)
- **Roles** — Role and permission management (create custom roles, edit permissions)

### Sync Control (`/sync`)
- Scheduler status (running/stopped, next run time)
- Last sync result (activities synced, chats synced, timestamp)
- Manual trigger button (runs in background)
- Live log viewer with auto-refresh and color-coded severity levels

---

## Purview Sync

The sync process replicates compliance data from the Anthropic API into Microsoft Purview via the Graph API, delivered as HTML email messages in a compliance mailbox.

### How it works

1. **Activity sync** — Fetches new activities since the last cursor, converts each to a formatted HTML email, and creates it in the target mailbox folder via Graph API
2. **Chat sync** — For chats referenced in new activities, fetches new messages since the last sync, downloads file attachments from Anthropic, and creates an email with the conversation thread and Base64-encoded MIME attachments
3. **State tracking** — Cursors and per-chat message counts are stored in Azure Table Storage for incremental syncing
4. **User filtering** — Configurable to archive all users or only a specific list of user IDs

### Requirements

- Anthropic Compliance Access Key
- Graph API credentials (Tenant ID, Client ID, Client Secret) or Key Vault
- Compliance mailbox email address
- Azure Storage connection string (provisioned by the ARM template)
- Graph API application permissions: `User.Read.All`, `Mail.ReadWrite`, `Mail.Send`

### Scheduling

- **Automatic** — Enable in Settings, set the cron expression (default: every 15 minutes)
- **Manual** — Click **Run Sync Now** on the Sync Control page
- **Monitoring** — Watch the live log viewer for real-time sync progress

---

## Azure Key Vault

CCompliance supports storing secrets in Azure Key Vault instead of config.json.

### How it works

- On Azure App Service, the web app's **system-assigned Managed Identity** authenticates to Key Vault (no credentials needed)
- Locally, falls back to Entra ID client credentials or `DefaultAzureCredential`
- When Key Vault mode is active, secrets are stripped from config.json and the setup wizard hides secret input fields

### Secrets managed

| Config Key | Default KV Secret Name |
|---|---|
| `anthropic_compliance_access_key` | `anthropic-compliance-access-key` |
| `graph_client_secret` | `graph-client-secret` |
| `storage_connection_string` | `storage-connection-string` |

### Setup

1. Create an Azure Key Vault in the same subscription
2. Enable the App Service's system-assigned Managed Identity (done by the ARM template)
3. Grant the Managed Identity **Key Vault Secrets User** access on the Key Vault
4. In the Setup Wizard (Step 4), enter your Key Vault URL, test the connection, and click **Migrate Secrets**

---

## Configuration Reference

Settings can be managed via the **Settings UI**, environment variables, or `config.json`. Priority: **Environment variables > config.json > defaults**.

### Anthropic Compliance API

| Setting | Env Variable | Default |
|---|---|---|
| Compliance Access Key | `ANTHROPIC_COMPLIANCE_ACCESS_KEY` | *(empty)* |
| Base URL | `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` |

### Microsoft Graph API

| Setting | Env Variable | Default |
|---|---|---|
| Tenant ID | `GRAPH_TENANT_ID` | *(empty)* |
| Client ID | `GRAPH_CLIENT_ID` | *(empty)* |
| Client Secret | `GRAPH_CLIENT_SECRET` | *(empty)* |

### Compliance Mailbox

| Setting | Env Variable | Default |
|---|---|---|
| Mailbox Email | `COMPLIANCE_MAILBOX` | *(empty)* |
| Folder Name | `COMPLIANCE_FOLDER_NAME` | `Anthropic Claude Archive` |
| Folder Hidden | `COMPLIANCE_FOLDER_HIDDEN` | `true` |

### Sync

| Setting | Env Variable | Default |
|---|---|---|
| Activity Batch Size | `ACTIVITY_BATCH_SIZE` | `500` |
| Chat Batch Size | `CHAT_BATCH_SIZE` | `100` |
| Ingest Chat Content | `INGEST_CHAT_CONTENT` | `true` |
| Sync Schedule (cron) | `SYNC_SCHEDULE_CRON` | `*/15 * * * *` |
| Sync Enabled | `SYNC_ENABLED` | `false` |

### Azure Storage

| Setting | Env Variable | Default |
|---|---|---|
| Connection String | `AzureWebJobsStorage` | *(empty)* |

### Branding

| Setting | Env Variable | Default |
|---|---|---|
| App Name | `BRAND_APP_NAME` | `CCompliance` |
| Sidebar Color | `BRAND_SIDEBAR_COLOR` | `#1a1a2e` |
| Accent Color | `BRAND_ACCENT_COLOR` | `#6b21a8` |

### Credential Storage

| Setting | Env Variable | Default |
|---|---|---|
| Storage Mode | `CREDENTIAL_STORAGE` | `local` |
| Key Vault URL | `KEYVAULT_URL` | *(empty)* |

### Entra ID Authentication (env vars only — never saved to config.json)

| Env Variable | Default | Description |
|---|---|---|
| `ENTRA_CLIENT_ID` | *(empty)* | Entra ID app registration client ID |
| `ENTRA_CLIENT_SECRET` | *(empty)* | Entra ID app registration client secret |
| `ENTRA_TENANT_ID` | *(empty)* | Azure AD tenant ID |
| `ENTRA_REDIRECT_URI` | `http://localhost:5000/getAToken` | OAuth2 redirect URI |
| `FLASK_SECRET_KEY` | *(auto-generated)* | Flask session encryption key |

### Bootstrap Admin (ARM template parameters)

| Env Variable | Description |
|---|---|
| `ADMIN_USERNAME` | Username for the initial Super Admin account |
| `ADMIN_PASSWORD` | Password for the initial Super Admin account |

---

## Troubleshooting

### Cannot log in after ARM template deployment
The ARM template seeds a Super Admin account and enables local authentication automatically. Go to `https://<appName>.azurewebsites.net/login` and sign in with the admin username and password you set during deployment.

### "Anthropic API not configured"
Go to **Settings > API Setup** and follow the setup wizard. Enter your Compliance Access Key in Step 3, test the connection, and save.

### Test Connection fails for Anthropic API
- Verify your key starts with `sk-ant-api01-`
- Check that SSL/TLS is not blocked by a corporate proxy
- The app disables SSL verification by default; remove the `ssl._create_default_https_context` override in `app.py` for strict SSL

### Sync not running
1. Ensure **Sync Enabled** is checked in Settings
2. Ensure all requirements are configured (Anthropic key, Graph credentials, mailbox, storage)
3. Check the Sync Control log for errors
4. The scheduler starts at app boot — restart the App Service after enabling sync

### Session lost / logged out unexpectedly
Set a fixed `FLASK_SECRET_KEY` environment variable. Without it, a random key is generated on each restart, invalidating existing sessions.

### Azure: 502 Bad Gateway
- Check that `startup.sh` is set as the startup command
- Verify the app starts locally before deploying
- Check App Service logs: **Azure Portal > App Service > Log stream**

### Key Vault: "could not read secret"
- Verify the App Service's Managed Identity has **Key Vault Secrets User** role on the Key Vault
- Check that the secret names in Settings match the actual secret names in Key Vault
- For local dev, ensure Entra ID client credentials are configured in `.env`

---

## Anthropic Compliance API Endpoints

This application provides a GUI for all 14 Anthropic Compliance API endpoints:

| # | Endpoint | GUI Location |
|---|---|---|
| 1 | `GET /v1/compliance/activities` | Activity Feed |
| 2 | `GET /v1/compliance/organizations` | Organizations |
| 3 | `GET /v1/compliance/organizations/{uuid}/users` | Organization > View Users |
| 4 | `GET /v1/compliance/apps/chats` | Chats |
| 5 | `GET /v1/compliance/apps/chats/{id}/messages` | Chat Detail |
| 6 | `DELETE /v1/compliance/apps/chats/{id}` | Chat Detail > Delete |
| 7 | `GET /v1/compliance/apps/chats/files/{id}/content` | Chat Detail > Download File |
| 8 | `DELETE /v1/compliance/apps/chats/files/{id}` | Chat Detail > Delete File |
| 9 | `GET /v1/compliance/apps/projects` | Projects |
| 10 | `GET /v1/compliance/apps/projects/{id}` | Project Detail |
| 11 | `DELETE /v1/compliance/apps/projects/{id}` | Project Detail > Delete |
| 12 | `GET /v1/compliance/apps/projects/{id}/attachments` | Project Detail > Attachments |
| 13 | `GET /v1/compliance/apps/projects/documents/{id}` | Project Document |
| 14 | `DELETE /v1/compliance/apps/projects/documents/{id}` | Project Document > Delete |
