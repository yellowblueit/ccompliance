"""
Sync service: extracts sync_activities and sync_chats logic from function_app.py
and adds an in-memory log ring buffer for the UI.
"""
import html
import base64
import logging
from datetime import datetime, timezone, timedelta
from collections import deque

# In-memory log buffer (most recent entries)
_log_buffer = deque(maxlen=500)
_sync_running = False
_sync_cancel_requested = False
_last_sync_result = None


def get_log_entries(limit=100):
    return list(_log_buffer)[-limit:]


def is_sync_running():
    return _sync_running


def get_last_sync_result():
    return _last_sync_result


def request_sync_cancel():
    """Request cancellation of the currently running sync."""
    global _sync_cancel_requested
    if _sync_running:
        _sync_cancel_requested = True
        return True
    return False


def _check_cancelled(logger):
    """Check if cancellation was requested. Returns True if sync should stop."""
    if _sync_cancel_requested:
        logger.warning("Sync cancelled by user.")
        return True
    return False


class SyncLogger:
    """Logger that writes to both Python logging and the in-memory buffer."""
    def __init__(self):
        self._logger = logging.getLogger("SyncService")
        self._logger.setLevel(logging.INFO)

    def _add(self, level, msg):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        _log_buffer.append({"time": ts, "level": level, "message": msg})
        getattr(self._logger, level.lower(), self._logger.info)(msg)

    def info(self, msg):
        self._add("INFO", msg)

    def warning(self, msg):
        self._add("WARNING", msg)

    def error(self, msg):
        self._add("ERROR", msg)


def get_target_mailbox(data, default_mailbox):
    actor = data.get("actor", {}) or {}
    if actor.get("type") == "user_actor" and actor.get("email_address"):
        return actor["email_address"]
    user = data.get("user", {}) or {}
    if user.get("email_address"):
        return user["email_address"]
    if actor.get("type") == "unauthenticated_user_actor":
        return actor.get("unauthenticated_email_address", "")
    return default_mailbox or ""



def chat_update_to_mail_message(chat_data, new_messages, file_attachments=None, msg_start=0, msg_end=0):
    user = chat_data.get("user", {}) or {}
    user_email = user.get("email_address", "unknown@unknown.com")
    chat_name = chat_data.get("name", "Untitled Chat")
    chat_id = chat_data.get("id", "")
    created_at = chat_data.get("created_at", "")
    updated_at = chat_data.get("updated_at", "")
    org_id = chat_data.get("organization_id", "N/A")
    project_id = chat_data.get("project_id", "N/A")
    total = len(chat_data.get("chat_messages") or [])
    is_new = msg_start == 0

    conv = ""
    for msg in new_messages:
        role = msg.get("role", "unknown")
        mt = msg.get("created_at", "")
        parts = msg.get("content") or []
        files = msg.get("files") or []
        if role == "user":
            rl, bg, bc, rc = "User", "#f0f7ff", "#cce0ff", "#0066cc"
        else:
            rl, bg, bc, rc = "Claude", "#f5f0ff", "#e0d0ff", "#6b21a8"
        txt = "".join(html.escape(p.get("text", "")) for p in parts if p.get("type") == "text")
        fhtml = ""
        if files:
            fi = "".join(
                f'<div style="display:inline-block;background:#fff;border:1px solid #ddd;border-radius:4px;'
                f'padding:4px 10px;margin:2px 4px 2px 0;font-size:12px">'
                f'<strong>{html.escape(f.get("filename", "?"))}</strong> '
                f'<span style="color:#888">({html.escape(f.get("mime_type", ""))})</span></div>'
                for f in files
            )
            fhtml = f'<div style="margin-top:8px">{fi}</div>'
        conv += (
            f'<div style="margin-bottom:16px;padding:14px;background:{bg};border-left:4px solid {bc};'
            f'border-radius:4px"><div style="font-weight:bold;color:{rc};margin-bottom:6px;font-size:13px">'
            f'{rl} <span style="font-weight:normal;color:#888;font-size:12px;margin-left:8px">'
            f'{html.escape(mt)}</span></div><div style="white-space:pre-wrap;line-height:1.5">{txt}</div>'
            f'{fhtml}</div>'
        )

    fc = f" | {len(file_attachments)} file(s) attached" if file_attachments else ""
    hdr = "Claude AI Chat Record" if is_new else "Claude AI Chat Update"
    mr = f"{total} messages" if is_new else f"Messages {msg_start + 1}-{msg_end} of {total}"

    body = f"""<html><body style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#333"><div style="max-width:800px">
<h2 style="color:#1a1a2e;border-bottom:2px solid #1a1a2e;padding-bottom:8px">{hdr}</h2>
<table style="border-collapse:collapse;width:100%;margin-bottom:24px;border:1px solid #ddd">
<tr style="background:#f5f5f5"><td style="padding:8px 12px;font-weight:bold;width:140px">Chat Name</td><td style="padding:8px 12px"><strong>{html.escape(str(chat_name))}</strong></td></tr>
<tr><td style="padding:8px 12px;font-weight:bold">Chat ID</td><td style="padding:8px 12px;font-family:monospace">{html.escape(chat_id)}</td></tr>
<tr><td style="padding:8px 12px;font-weight:bold">User</td><td style="padding:8px 12px">{html.escape(user_email)}</td></tr>
<tr><td style="padding:8px 12px;font-weight:bold">Organization</td><td style="padding:8px 12px;font-family:monospace">{html.escape(str(org_id))}</td></tr>
<tr><td style="padding:8px 12px;font-weight:bold">Project</td><td style="padding:8px 12px;font-family:monospace">{html.escape(str(project_id))}</td></tr>
<tr><td style="padding:8px 12px;font-weight:bold">Created (UTC)</td><td style="padding:8px 12px">{html.escape(created_at)}</td></tr>
<tr><td style="padding:8px 12px;font-weight:bold">Last Updated (UTC)</td><td style="padding:8px 12px">{html.escape(updated_at)}</td></tr>
<tr><td style="padding:8px 12px;font-weight:bold">Messages</td><td style="padding:8px 12px">{mr}</td></tr>
</table>
<h3 style="color:#555">{"Conversation" if is_new else "New Messages"}</h3>{conv}
<hr style="margin-top:30px;border:none;border-top:1px solid #ddd"/><p style="color:#999;font-size:11px">Anthropic-Exchange Compliance Connector{fc}</p></div></body></html>"""

    subj = (
        f"[Claude Chat] {chat_name or 'Untitled'} - {chat_id}"
        if is_new
        else f"[Claude Chat Update] {chat_name or 'Untitled'} - {chat_id} (msgs {msg_start + 1}-{msg_end})"
    )
    m = {
        "subject": subj,
        "receivedDateTime": updated_at or created_at or datetime.now(timezone.utc).isoformat(),
        "from": {"emailAddress": {"name": "Claude AI Compliance", "address": "claude-compliance@anthropic.com"}},
        "toRecipients": [{"emailAddress": {"name": user_email, "address": user_email}}],
        "body": {"contentType": "HTML", "content": body},
        "categories": ["Claude AI Compliance", "Chat Record" if is_new else "Chat Update"],
        "importance": "normal", "isRead": True,
    }
    if file_attachments:
        m["attachments"] = file_attachments
    return m


def collect_file_ids(messages):
    files, seen = [], set()
    for msg in messages:
        for f in (msg.get("files") or []):
            fid = f.get("id")
            if fid and fid not in seen:
                seen.add(fid)
                files.append({
                    "id": fid,
                    "filename": f.get("filename", fid),
                    "mime_type": f.get("mime_type", "application/octet-stream"),
                })
    return files


def sync_chats(anthropic, graph, state, logger, config):
    """Query chats directly via the Compliance API and sync new messages to Exchange."""
    archive_all = config.get("archive_all_users", False)
    archive_user_ids = list(config.get("archive_user_ids", []))

    if not archive_all and not archive_user_ids:
        logger.info("No users selected for archiving. Skipping chat sync.")
        return 0

    compliance_mailbox = config.get("compliance_mailbox", "")
    compliance_folder = config.get("compliance_folder_name", "Anthropic Claude Archive")
    folder_hidden = config.get("compliance_folder_hidden", True)
    batch_size = config.get("chat_batch_size", 100)

    # Incremental: use cursor timestamp, default to 24h lookback on first run
    last_ts = state.get_cursor("chat_last_ts")
    if not last_ts:
        last_ts = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    total = 0
    folder_cache = {}
    after_id = None

    while True:
        if _check_cancelled(logger):
            return total

        try:
            kwargs = {"updated_at_gte": last_ts, "limit": batch_size}
            if after_id:
                kwargs["after_id"] = after_id
            if not archive_all:
                kwargs["user_ids"] = archive_user_ids
            r = anthropic.list_chats(**kwargs)
        except Exception as e:
            logger.error(f"Chat list fetch: {e}")
            break

        chats = r.get("data", [])
        if not chats:
            break

        logger.info(f"Fetched {len(chats)} updated chat(s)...")

        for chat in chats:
            if _check_cancelled(logger):
                return total

            cid = chat.get("id")
            if not cid:
                continue

            try:
                cf = anthropic.get_chat_messages(cid)
                msgs = cf.get("chat_messages") or []
                tc = len(msgs)
                pc = state.get_chat_msg_count(cid)

                if tc <= pc:
                    continue

                new_msgs = msgs[pc:]
                logger.info(f"Chat {cid}: {len(new_msgs)} new msg(s) ({pc}->{tc})")

                fas = []
                for fr in collect_file_ids(new_msgs):
                    try:
                        content, fn, mt = anthropic.download_file(fr["id"])
                        fas.append({
                            "@odata.type": "#microsoft.graph.fileAttachment",
                            "name": fr["filename"],
                            "contentType": fr["mime_type"],
                            "contentBytes": base64.b64encode(content).decode(),
                        })
                    except Exception as e:
                        logger.warning(f"File {fr['id']}: {e}")

                mb = get_target_mailbox(cf, compliance_mailbox)
                if not mb:
                    continue
                if mb not in folder_cache:
                    folder_cache[mb] = graph.get_or_create_folder(mb, compliance_folder, is_hidden=folder_hidden)

                m = chat_update_to_mail_message(cf, new_msgs, file_attachments=fas, msg_start=pc, msg_end=tc)
                graph.create_message(mb, folder_cache[mb], m)
                total += 1
                state.set_chat_msg_count(cid, tc)
            except Exception as e:
                logger.error(f"Chat {cid}: {e}")

        after_id = r.get("last_id")
        if not r.get("has_more", False):
            break

    # Update cursor to now so next sync picks up from here
    state.set_cursor("chat_last_ts", datetime.now(timezone.utc).isoformat())
    logger.info(f"Chats synced: {total}")
    return total


def run_sync(config):
    """Run a full sync cycle. Called by scheduler or manual trigger."""
    global _sync_running, _sync_cancel_requested, _last_sync_result
    if _sync_running:
        return {"error": "Sync already running"}

    _sync_running = True
    _sync_cancel_requested = False
    logger = SyncLogger()
    archive_all = config.get("archive_all_users", False)
    archive_ids = config.get("archive_user_ids", [])
    if archive_all:
        logger.info("Starting sync... (all users, including future)")
    elif archive_ids:
        logger.info(f"Starting sync... ({len(archive_ids)} user(s) selected)")
    else:
        logger.info("Starting sync... (no users selected — nothing will be synced)")

    key = config.get("anthropic_compliance_access_key")
    if not key:
        logger.error("Missing Anthropic compliance key.")
        _sync_running = False
        return {"error": "Missing Anthropic compliance key"}

    if not all([config.get("graph_tenant_id"), config.get("graph_client_id"), config.get("graph_client_secret")]):
        logger.error("Missing Microsoft Graph credentials.")
        _sync_running = False
        return {"error": "Missing Microsoft Graph credentials"}

    if not config.get("storage_connection_string"):
        logger.error("Missing Azure Storage connection string.")
        _sync_running = False
        return {"error": "Missing Azure Storage connection string"}

    from clients.anthropic_client import AnthropicComplianceClient
    from clients.graph_client import GraphClient
    from clients.state_manager import StateManager

    ac = AnthropicComplianceClient(key, config.get("anthropic_base_url", "https://api.anthropic.com"))
    gc = GraphClient(config["graph_tenant_id"], config["graph_client_id"], config["graph_client_secret"])
    sm = StateManager(config["storage_connection_string"])

    c_count = 0
    try:
        c_count = sync_chats(ac, gc, sm, logger, config)
    except Exception as e:
        logger.error(f"Chat sync failed: {e}")

    cancelled = _sync_cancel_requested
    result = {
        "chats_synced": c_count,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "cancelled": cancelled,
    }
    if cancelled:
        logger.warning(f"Sync stopped by user: {c_count} chat(s) synced before cancellation.")
    else:
        logger.info(f"Sync complete: {c_count} chat(s) synced.")
    _last_sync_result = result
    _sync_running = False
    _sync_cancel_requested = False
    return result
