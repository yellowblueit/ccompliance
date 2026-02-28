# CCompliance API Explorer & Purview Sync

A Flask web application that provides a full interactive GUI for the **Anthropic Compliance API** (Rev E) and optionally syncs compliance data to **Microsoft Purview** via the Graph API. Secured with **Microsoft Entra ID** authentication.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Local Development Setup](#local-development-setup)
- [Azure Deployment](#azure-deployment)
- [Configuration Reference](#configuration-reference)
- [Authentication](#authentication)
- [Pages & Functionality](#pages--functionality)
- [Purview Sync](#purview-sync)
- [Troubleshooting](#troubleshooting)

---

## Features

| Feature | Description |
|---|---|
| **Activity Feed** | Browse, filter, and inspect all compliance activities (authentication events, chat operations, file uploads, project changes, API key events, org changes) with full pagination |
| **Organizations** | List all organizations and drill into user rosters per org |
| **Chat Explorer** | Search chats by user, org, project, and date ranges. View full conversation threads with message styling, download attached files, delete chats |
| **Project Browser** | Browse projects, view details and prompt templates, inspect attachments, view/delete documents |
| **Settings Editor** | Web form to configure all API keys, connection strings, batch sizes, and sync schedules. Test connection buttons for Anthropic and Graph APIs. Download `config.json` |
| **Purview Sync** | Background scheduler syncs activities and chat updates to Microsoft Purview (via Graph API mail messages). Manual trigger and live log viewer |
| **Entra ID Auth** | Microsoft Entra ID (Azure AD) login restricted to your tenant. Dev mode fallback when not configured |

---

## Architecture

```
CCompliance/
├── app.py                          # Flask app factory & entry point
├── config.py                       # Config loader (config.json + env fallbacks)
├── auth.py                         # Entra ID authentication setup
├── requirements.txt                # Python dependencies
├── startup.sh                      # Azure App Service startup command
├── .env.example                    # Environment variable template
│
├── clients/
│   ├── anthropic_client.py         # Anthropic Compliance API (all 14 endpoints)
│   ├── graph_client.py             # Microsoft Graph API (mail/folder operations)
│   └── state_manager.py            # Azure Table Storage (sync cursor tracking)
│
├── services/
│   ├── sync_service.py             # Purview sync logic (activities + chats)
│   └── scheduler_service.py        # APScheduler background sync wrapper
│
├── routes/
│   ├── __init__.py                 # Shared helpers (login_required, get_anthropic_client)
│   ├── dashboard.py                # Dashboard overview page
│   ├── settings.py                 # Config editor & connection testing
│   ├── activities.py               # Activity feed browser
│   ├── organizations.py            # Organization & user browser
│   ├── chats.py                    # Chat search, message viewer, file download
│   ├── projects.py                 # Project browser, attachments, documents
│   └── sync_control.py             # Manual sync trigger & log viewer
│
├── templates/                      # Jinja2 HTML templates (Bootstrap 5)
│   ├── base.html                   # Master layout (sidebar, topbar, flash messages)
│   ├── dashboard.html
│   ├── settings.html
│   ├── activities/                 # list.html, detail.html
│   ├── organizations/              # list.html, users.html
│   ├── chats/                      # list.html, detail.html
│   ├── projects/                   # list.html, detail.html, document.html
│   └── sync/                       # control.html
│
├── static/
│   ├── css/custom.css              # Anthropic brand styling
│   └── js/app.js                   # Delete modals, sync log polling
│
├── function_app.py                 # Original Azure Function (preserved for reference)
└── test_sync_v4.py                 # Original test script (preserved for reference)
```

**Key design decisions:**
- **Single gunicorn worker** — APScheduler is not process-safe; one worker prevents duplicate sync runs
- **Config layering** — `config.json` values are overridden by environment variables (Azure App Settings always win)
- **Entra ID secrets never saved to config.json** — always loaded from environment variables for security
- **Bootstrap 5 via CDN** — no frontend build step required

---

## Prerequisites

- **Python 3.10+** (tested with 3.14)
- **Anthropic Compliance API access key** (`sk-ant-api01-...`)
- *Optional:* Microsoft Entra ID app registration (for production authentication)
- *Optional:* Microsoft Graph API credentials (for Purview sync)
- *Optional:* Azure Storage account (for sync state persistence)

---

## Local Development Setup

### 1. Install dependencies

```powershell
# If 'python' is aliased to the Microsoft Store stub, use the full path:
& "C:\Users\<you>\AppData\Local\Python\bin\python.exe" -m pip install -r requirements.txt

# Or if python is on your PATH:
python -m pip install -r requirements.txt
```

**Tip:** To fix the "Python was not found" error on Windows 11, go to **Settings > Apps > Advanced app settings > App execution aliases** and toggle off the `python.exe` and `python3.exe` Microsoft Store entries.

### 2. Create your environment file

```powershell
copy .env.example .env
```

Edit `.env` and at minimum set:

```ini
# Required for the app to function:
ANTHROPIC_COMPLIANCE_ACCESS_KEY=sk-ant-api01-your-key-here

# Optional — leave blank to run in dev mode (no login required):
# ENTRA_CLIENT_ID=
# ENTRA_CLIENT_SECRET=
# ENTRA_TENANT_ID=
```

### 3. Run the application

```powershell
& "C:\Users\<you>\AppData\Local\Python\bin\python.exe" app.py

# Or if python is on your PATH:
python app.py
```

The app starts at **http://localhost:5000**. In dev mode (no Entra ID configured), you're automatically logged in as "Dev User".

### 4. First-time configuration

1. Navigate to **http://localhost:5000**
2. Go to **Settings** in the sidebar
3. Enter your **Anthropic Compliance Access Key**
4. Click **Test Connection** to verify
5. Click **Save Settings**
6. Start browsing the **Activity Feed**, **Chats**, **Projects**, etc.

---

## Azure Deployment

### Recommended: Azure App Service B1 Basic (~$13/month)

### 1. Create an App Service

```bash
az webapp create \
  --resource-group your-rg \
  --plan your-plan \
  --name ccompliance \
  --runtime "PYTHON:3.12"
```

### 2. Configure App Settings

Set these in **Azure Portal > App Service > Configuration > Application settings** (or via CLI):

```bash
# Required
az webapp config appsettings set --name ccompliance --resource-group your-rg --settings \
  ANTHROPIC_COMPLIANCE_ACCESS_KEY="sk-ant-api01-..." \
  FLASK_SECRET_KEY="$(openssl rand -hex 32)"

# Entra ID authentication
az webapp config appsettings set --name ccompliance --resource-group your-rg --settings \
  ENTRA_CLIENT_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" \
  ENTRA_CLIENT_SECRET="your-client-secret" \
  ENTRA_TENANT_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" \
  ENTRA_REDIRECT_URI="https://ccompliance.azurewebsites.net/getAToken"

# Purview sync (optional)
az webapp config appsettings set --name ccompliance --resource-group your-rg --settings \
  GRAPH_TENANT_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" \
  GRAPH_CLIENT_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" \
  GRAPH_CLIENT_SECRET="your-graph-secret" \
  COMPLIANCE_MAILBOX="compliance@yourorg.com" \
  AzureWebJobsStorage="DefaultEndpointsProtocol=https;AccountName=..."
```

### 3. Set the startup command

```bash
az webapp config set --name ccompliance --resource-group your-rg \
  --startup-file "startup.sh"
```

The startup script runs:
```bash
gunicorn --bind=0.0.0.0:8000 --timeout 600 --workers 1 app:app
```

### 4. Deploy code

Upload the project files via ZIP deploy, Git deploy, or VS Code Azure extension:

```bash
az webapp deploy --resource-group your-rg --name ccompliance \
  --src-path ./deploy.zip --type zip
```

### 5. Register Entra ID app

1. Go to **Azure Portal > Entra ID > App registrations > New registration**
2. Set redirect URI to `https://ccompliance.azurewebsites.net/getAToken`
3. Under **API permissions**, add `User.Read` (Microsoft Graph)
4. Under **Certificates & secrets**, create a client secret
5. Copy the **Application (client) ID**, **Directory (tenant) ID**, and **Client secret** to your App Settings

---

## Configuration Reference

All settings can be managed via the **Settings** page in the web UI, environment variables, or by editing `config.json` directly.

**Priority order:** Environment variables > config.json > defaults

### Anthropic Compliance API

| Setting | Env Variable | Default | Description |
|---|---|---|---|
| Compliance Access Key | `ANTHROPIC_COMPLIANCE_ACCESS_KEY` | *(empty)* | Your Anthropic compliance API key (`sk-ant-api01-...`) |
| Base URL | `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | API endpoint (change only for proxies or testing) |

### Microsoft Graph API (for Purview Sync)

| Setting | Env Variable | Default | Description |
|---|---|---|---|
| Tenant ID | `GRAPH_TENANT_ID` | *(empty)* | Azure AD tenant ID for Graph API |
| Client ID | `GRAPH_CLIENT_ID` | *(empty)* | App registration client ID |
| Client Secret | `GRAPH_CLIENT_SECRET` | *(empty)* | App registration client secret |

### Compliance Mailbox

| Setting | Env Variable | Default | Description |
|---|---|---|---|
| Mailbox Email | `COMPLIANCE_MAILBOX` | *(empty)* | Target mailbox for compliance records (e.g., `compliance@yourorg.com`) |
| Folder Name | `COMPLIANCE_FOLDER_NAME` | `Claude AI Compliance` | Mail folder name created in the target mailbox |

### Sync Settings

| Setting | Env Variable | Default | Description |
|---|---|---|---|
| Activity Batch Size | `ACTIVITY_BATCH_SIZE` | `500` | Number of activities to fetch per API call |
| Chat Batch Size | `CHAT_BATCH_SIZE` | `100` | Number of chats to fetch per API call |
| Ingest Chat Content | `INGEST_CHAT_CONTENT` | `true` | Whether to sync chat messages and attachments to Purview |
| Sync Schedule (cron) | `SYNC_SCHEDULE_CRON` | `*/15 * * * *` | Standard 5-field cron expression for auto-sync |
| Sync Enabled | `SYNC_ENABLED` | `false` | Enable/disable the automatic background sync |

### Azure Storage

| Setting | Env Variable | Default | Description |
|---|---|---|---|
| Connection String | `AzureWebJobsStorage` | *(empty)* | Azure Table Storage connection string for sync state (cursor tracking) |

### Entra ID Authentication (env vars only — never saved to config.json)

| Env Variable | Default | Description |
|---|---|---|
| `ENTRA_CLIENT_ID` | *(empty)* | Entra ID app registration client ID |
| `ENTRA_CLIENT_SECRET` | *(empty)* | Entra ID app registration client secret |
| `ENTRA_TENANT_ID` | *(empty)* | Your Azure AD tenant ID (restricts login to your org) |
| `ENTRA_REDIRECT_URI` | `http://localhost:5000/getAToken` | OAuth2 redirect URI (update for production) |
| `FLASK_SECRET_KEY` | *(auto-generated)* | Flask session encryption key (set a fixed value in production) |

---

## Authentication

### Production (Entra ID)

When `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`, and `ENTRA_TENANT_ID` are all set:
- Users are redirected to Microsoft login on first visit
- Only users in your tenant can sign in
- Sessions are managed by Flask's server-side session store

### Development Mode

When Entra ID is **not** configured:
- No login is required
- A mock "Dev User" session is automatically created
- All routes are accessible immediately
- A console warning is logged: *"Entra ID not configured — running in dev mode"*

---

## Pages & Functionality

### Dashboard (`/dashboard`)
Overview page showing connection status for all configured services (Anthropic API, Graph API, Purview Sync, Mailbox). Quick action links and a getting-started checklist.

### Activity Feed (`/activities`)
Full-featured activity browser with filters:
- **Date range** — `created_at` greater/less than (UTC)
- **Organization IDs** — comma-separated list
- **Actor IDs** — comma-separated list
- **Activity Types** — comma-separated (e.g., `claude_chat_created, sso_login_succeeded`)
- **Limit** — 25, 50, 100, 250, 500, or 1000 results

Click any row to view full event details, actor information, additional fields, and raw JSON.

**Supported activity type categories:**
- Authentication (SSO, magic link, logout, session, phone verification)
- Chats (created, updated, viewed, deleted, settings)
- Files (uploaded, deleted, viewed)
- Projects (created, deleted, archived, sharing, documents)
- API (key created, compliance API accessed)
- Organization (settings, user management, roles)

### Organizations (`/organizations`)
Lists all organizations accessible via your compliance key. Click **View Users** to drill into the user roster for any org, with pagination.

### Chats (`/chats`)
Search and browse chats with filters:
- **User IDs** — comma-separated
- **Organization IDs** — comma-separated
- **Project IDs** — comma-separated
- **Created/Updated date ranges** — UTC datetime pickers
- **Limit** — results per page

**Chat Detail view:**
- Full conversation thread with user/Claude message styling
- File attachments with download links
- Delete chat (requires typing the chat ID to confirm)

### Projects (`/projects`)
Browse projects with filters:
- **Organization IDs**, **User IDs** — comma-separated
- **Date range**, **Limit**

**Project Detail view:**
- Project metadata (name, description, visibility, creator, dates)
- Prompt template display
- Attachments table with links to view individual documents
- Delete project (requires typing the project ID to confirm)

**Document view:**
- Document metadata (filename, type, size, created date)
- Document content preview
- Delete document with confirmation

### Settings (`/settings`)
Web form to configure:
- **Anthropic Compliance API** — key and base URL, with **Test Connection** button
- **Microsoft Graph API** — tenant, client ID, client secret, with **Test Connection** button
- **Compliance Mailbox** — email address and folder name
- **Sync Settings** — batch sizes, cron schedule, chat ingestion toggle, sync enable/disable
- **Azure Storage** — connection string for state persistence
- **Download config.json** button to export current settings

### Sync Control (`/sync`)
- **Scheduler status** — running/stopped, next scheduled run time
- **Last sync result** — activities synced, chats synced, completion timestamp
- **Manual trigger** — "Run Sync Now" button (runs in background thread)
- **Live log viewer** — auto-refreshing (every 3 seconds) scrollable log with color-coded severity levels (INFO, WARNING, ERROR)

---

## Purview Sync

The sync process replicates compliance data from the Anthropic API into Microsoft Purview via the Graph API (as mail messages in a compliance mailbox).

### How it works

1. **Activity sync** — Fetches new activities since the last cursor, converts each to an HTML email, and creates it in the target mailbox folder via Graph API
2. **Chat sync** — For any chats referenced in new activities, fetches new messages since the last sync, downloads file attachments, and creates an email with the conversation thread and attachments
3. **State tracking** — Cursors (`act_last_id`, `act_last_ts`) and per-chat message counts are stored in Azure Table Storage so syncs are incremental

### Requirements for sync

All of the following must be configured:
- Anthropic Compliance Access Key
- Graph API credentials (tenant ID, client ID, client secret)
- Compliance mailbox email address
- Azure Storage connection string

### Scheduling

- **Automatic:** Enable in Settings, set the cron expression (default: every 15 minutes)
- **Manual:** Click "Run Sync Now" on the Sync Control page
- **Monitoring:** Watch the live log viewer for real-time sync progress

---

## Troubleshooting

### "Python was not found" on Windows 11
The Microsoft Store app alias intercepts the `python` command. Fix:
1. Go to **Settings > Apps > Advanced app settings > App execution aliases**
2. Toggle **off** both `python.exe` and `python3.exe`
3. Or use the full path: `& "C:\Users\<you>\AppData\Local\Python\bin\python.exe" app.py`

### "Anthropic API not configured" on every page
Go to **Settings**, enter your Compliance Access Key, click **Test Connection**, then **Save Settings**.

### Test Connection fails for Anthropic API
- Verify your key starts with `sk-ant-api01-`
- Check that SSL/TLS is not being blocked by a corporate proxy
- The app disables SSL verification by default; if you need strict SSL, remove the `ssl._create_default_https_context` override in `app.py`

### Sync not running automatically
1. Ensure **Sync Enabled** is checked in Settings
2. Ensure all four requirements are configured (Anthropic key, Graph credentials, mailbox, storage)
3. Check the Sync Control log for errors
4. The scheduler only starts when the app boots — restart the app after enabling sync

### Session lost / logged out unexpectedly
Set a fixed `FLASK_SECRET_KEY` environment variable. Without it, a random key is generated on each restart, invalidating existing sessions.

### Azure deployment: 502 Bad Gateway
- Check that `startup.sh` is set as the startup command
- Verify the app starts locally before deploying
- Check App Service logs: **Azure Portal > App Service > Log stream**

---

## API Endpoints Covered

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
