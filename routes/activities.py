import hashlib
import io
import json
import time
import zipfile
import requests as http_requests
from flask import (Blueprint, render_template, request, session,
                   Response, flash, redirect, url_for, jsonify, current_app,
                   stream_with_context)
from routes import login_required, get_anthropic_client, get_graph_client

activities_bp = Blueprint("activities", __name__)

ACTIVITY_TYPE_CATEGORIES = {
    "Authentication": [
        "sso_login_initiated", "sso_login_succeeded", "sso_login_failed",
        "social_login_succeeded", "magic_link_login_initiated",
        "magic_link_login_succeeded", "magic_link_login_failed",
        "user_logged_out", "session_revoked", "age_verified",
        "phone_code_sent", "phone_code_verified",
        "anonymous_mobile_login_attempted", "sso_second_factor_magic_link",
    ],
    "Chats": [
        "claude_chat_created", "claude_chat_updated", "claude_chat_viewed",
        "claude_chat_deleted", "claude_chat_deletion_failed",
        "claude_chat_access_failed", "claude_chat_settings_updated",
    ],
    "Files": [
        "claude_file_uploaded", "claude_file_deleted",
        "claude_file_viewed", "claude_file_access_failed",
    ],
    "Projects": [
        "claude_project_created", "claude_project_deleted",
        "claude_project_viewed", "claude_project_archived",
        "claude_project_sharing_updated", "claude_project_reported",
        "claude_project_document_uploaded", "claude_project_document_deleted",
        "claude_project_document_viewed",
    ],
    "API": [
        "api_key_created", "compliance_api_accessed",
    ],
    "Organization": [
        "claude_organization_settings_updated", "org_user_deleted",
        "org_user_invite_sent", "org_user_invite_accepted",
        "claude_user_role_updated", "claude_user_settings_updated",
    ],
    "Artifacts": [
        "claude_artifact_created", "claude_artifact_updated",
        "claude_artifact_viewed", "claude_artifact_deleted",
        "claude_artifact_shared",
    ],
    "Billing": [
        "billing_plan_changed", "billing_seat_added",
        "billing_seat_removed", "billing_payment_method_updated",
        "billing_subscription_created", "billing_subscription_cancelled",
        "billing_invoice_generated",
    ],
    "Chat Snapshots": [
        "claude_chat_snapshot_created", "claude_chat_snapshot_viewed",
        "claude_chat_snapshot_deleted", "claude_chat_snapshot_shared",
    ],
    "Customizations": [
        "claude_customization_created", "claude_customization_updated",
        "claude_customization_deleted",
    ],
    "Groups": [
        "group_created", "group_updated", "group_deleted",
        "group_member_added", "group_member_removed",
    ],
    "Integrations": [
        "integration_created", "integration_updated",
        "integration_deleted", "integration_enabled",
        "integration_disabled",
    ],
    "SSO & Directory Sync": [
        "sso_configuration_created", "sso_configuration_updated",
        "sso_configuration_deleted", "directory_sync_enabled",
        "directory_sync_disabled", "directory_sync_completed",
        "directory_sync_failed",
    ],
    "Service Keys": [
        "service_key_created", "service_key_updated",
        "service_key_deleted", "service_key_rotated",
    ],
    "Session Shares": [
        "session_share_created", "session_share_viewed",
        "session_share_deleted", "session_share_revoked",
    ],
}

FILE_ACTIVITY_TYPES = {
    "claude_file_uploaded", "claude_file_deleted",
    "claude_file_viewed", "claude_file_access_failed",
}

CHAT_ACTIVITY_TYPES = {
    "claude_chat_created", "claude_chat_updated", "claude_chat_viewed",
    "claude_chat_deleted", "claude_chat_deletion_failed",
    "claude_chat_access_failed", "claude_chat_settings_updated",
}

# App-level org name cache (avoids repeated API calls)
_org_cache = {"data": {}, "ts": 0}
_ORG_CACHE_TTL = 300  # 5 minutes

# Short-lived list cache: avoids re-hitting the API when the user navigates
# back from a detail page or refreshes with the same filters.
_list_cache = {}       # cache_key -> (timestamp, result_dict)
_LIST_CACHE_TTL = 60   # 60 seconds


def _list_cache_key(kwargs):
    """Stable MD5 key for a list_activities kwargs dict."""
    normalized = {k: sorted(v) if isinstance(v, list) else v
                  for k, v in kwargs.items()}
    return hashlib.md5(json.dumps(normalized, sort_keys=True).encode()).hexdigest()

# Activity cache: full records keyed by ID, used for detail page lazy-load
_activity_cache = {}       # id -> (timestamp, full_dict)
_ACTIVITY_CACHE_TTL = 600  # 10 minutes
_ACTIVITY_CACHE_MAX = 2000


def _cache_activities(activities):
    """Cache full activity records server-side for detail page lookups."""
    now = time.time()
    for a in activities:
        aid = a.get("id")
        if aid:
            _activity_cache[aid] = (now, a)
    # Prune oldest if over max
    if len(_activity_cache) > _ACTIVITY_CACHE_MAX:
        by_age = sorted(_activity_cache, key=lambda k: _activity_cache[k][0])
        for aid in by_age[:len(_activity_cache) - _ACTIVITY_CACHE_MAX]:
            del _activity_cache[aid]


def _slim_activity(a):
    """Extract only the fields needed for table display."""
    actor = a.get("actor") or {}
    return {
        "id": a.get("id", ""),
        "created_at": a.get("created_at", ""),
        "type": a.get("type", ""),
        "organization_id": a.get("organization_id", ""),
        "actor_email": (actor.get("email_address")
                        or actor.get("unauthenticated_email_address")
                        or actor.get("api_key_id") or ""),
        "file_id": _extract_file_id(a),
    }


def _extract_file_id(activity):
    """Pull a file ID from an activity record, checking common field names."""
    if activity.get("type") not in FILE_ACTIVITY_TYPES:
        return None
    for key in ("claude_file_id", "file_id", "claude_chat_file_id"):
        val = activity.get(key)
        if val:
            return val
    f = activity.get("file") or activity.get("claude_file") or {}
    if isinstance(f, dict):
        return f.get("id") or f.get("file_id")
    return None


def _extract_chat_id(activity):
    """Extract chat ID from chat-related activity."""
    if activity.get("type") not in CHAT_ACTIVITY_TYPES:
        return None
    for key in ("claude_chat_id", "chat_id"):
        val = activity.get(key)
        if val:
            return val
    chat = activity.get("chat") or activity.get("claude_chat") or {}
    if isinstance(chat, dict):
        return chat.get("id") or chat.get("chat_id")
    return None


# ── Page routes (no blocking API calls besides the primary data) ──


@activities_bp.route("/")
@login_required
def index():
    # Render the page shell immediately — data loads via AJAX for speed.
    selected_types = request.args.getlist("activity_types")
    filters = {
        "created_at_gte": request.args.get("created_at_gte", ""),
        "created_at_lte": request.args.get("created_at_lte", ""),
        "organization_ids": request.args.get("organization_ids", ""),
        "actor_ids": request.args.get("actor_ids", ""),
        "activity_types": selected_types,
        "after_id": request.args.get("after_id", ""),
        "before_id": request.args.get("before_id", ""),
        "limit": request.args.get("limit", "50"),
    }
    return render_template("activities/list.html",
                           filters=filters,
                           user=session.get("user", {}),
                           activity_types=ACTIVITY_TYPE_CATEGORIES)


@activities_bp.route("/api/list")
@login_required
def api_list():
    """Return activity list as JSON for async table loading."""
    client = get_anthropic_client()
    if not client:
        return jsonify({"error": "Anthropic API not configured. Go to Settings.",
                        "data": [], "has_more": False})

    kwargs = {"limit": int(request.args.get("limit", 50) or 50)}
    for key in ("created_at_gte", "created_at_lte", "after_id", "before_id"):
        v = request.args.get(key, "")
        if v:
            kwargs[key] = v
    for key in ("organization_ids", "actor_ids"):
        v = request.args.get(key, "")
        if v:
            kwargs[key] = [x.strip() for x in v.split(",") if x.strip()]
    types = request.args.getlist("activity_types")
    if types:
        kwargs["activity_types"] = types

    try:
        cache_key = _list_cache_key(kwargs)
        cached = _list_cache.get(cache_key)
        if cached and (time.time() - cached[0]) < _LIST_CACHE_TTL:
            result = cached[1]
        else:
            result = client.list_activities(**kwargs)
            _list_cache[cache_key] = (time.time(), result)
        full = result.get("data", [])
        _cache_activities(full)  # cache full records for detail lookups
        return jsonify({
            "data": [_slim_activity(a) for a in full],
            "has_more": result.get("has_more", False),
            "last_id": result.get("last_id"),
            "first_id": result.get("first_id"),
        })
    except Exception as e:
        return jsonify({"error": str(e), "data": [], "has_more": False})


@activities_bp.route("/api/stream")
@login_required
def api_stream():
    """
    Server-Sent Events endpoint: push activity records to the client
    one-by-one as soon as they arrive from the Anthropic API.
    This lets the browser render rows progressively instead of waiting
    for the full JSON payload to arrive.
    """
    client = get_anthropic_client()

    # Build kwargs from query string (identical to api_list)
    kwargs = {"limit": int(request.args.get("limit", 50) or 50)}
    for key in ("created_at_gte", "created_at_lte", "after_id", "before_id"):
        v = request.args.get(key, "")
        if v:
            kwargs[key] = v
    for key in ("organization_ids", "actor_ids"):
        v = request.args.get(key, "")
        if v:
            kwargs[key] = [x.strip() for x in v.split(",") if x.strip()]
    types = request.args.getlist("activity_types")
    if types:
        kwargs["activity_types"] = types

    def generate():
        # Yield an SSE comment immediately so the browser's EventSource
        # receives response headers right away — before the API call starts.
        # This prevents the "stuck spinner" caused by the blocking API request.
        yield ': ping\n\n'

        if not client:
            yield f'event: stream_error\ndata: {json.dumps({"error": "Anthropic API not configured. Go to Settings."})}\n\n'
            return

        try:
            # Use the short-lived list cache so navigating back from a detail
            # page (or re-running the same filter) is instant.
            cache_key = _list_cache_key(kwargs)
            cached = _list_cache.get(cache_key)
            if cached and (time.time() - cached[0]) < _LIST_CACHE_TTL:
                result = cached[1]
            else:
                result = client.list_activities(**kwargs)
                _list_cache[cache_key] = (time.time(), result)
                # Prune cache to avoid unbounded growth
                if len(_list_cache) > 200:
                    oldest = sorted(_list_cache, key=lambda k: _list_cache[k][0])
                    for k in oldest[:50]:
                        del _list_cache[k]

            full = result.get("data", [])
            _cache_activities(full)

            # Yield each slim record as an individual SSE message so the
            # browser can render rows as they arrive.
            for a in full:
                yield f'data: {json.dumps(_slim_activity(a))}\n\n'

            meta = {
                "has_more": result.get("has_more", False),
                "last_id": result.get("last_id"),
                "first_id": result.get("first_id"),
                "count": len(full),
            }
            yield f'event: done\ndata: {json.dumps(meta)}\n\n'

        except Exception as e:
            yield f'event: stream_error\ndata: {json.dumps({"error": str(e)})}\n\n'

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Disable nginx/proxy buffering
        },
    )


@activities_bp.route("/api/activity/<activity_id>")
@login_required
def api_activity(activity_id):
    """Return full activity record from server-side cache."""
    entry = _activity_cache.get(activity_id)
    if entry:
        ts, data = entry
        if time.time() - ts < _ACTIVITY_CACHE_TTL:
            return jsonify(data)
        del _activity_cache[activity_id]
    return jsonify({"error": "Activity not in cache. Please go back to the activity list.",
                    "id": activity_id})


@activities_bp.route("/<activity_id>")
@login_required
def detail(activity_id):
    # Activity data is loaded client-side from sessionStorage for speed.
    # Pass the ID so the template JS can hydrate.
    return render_template("activities/detail.html",
                           activity_id=activity_id,
                           activity_type_cats=ACTIVITY_TYPE_CATEGORIES,
                           user=session.get("user", {}))


# ── AJAX endpoints (loaded async after page renders) ─────────


@activities_bp.route("/api/org-names")
@login_required
def api_org_names():
    """Return org ID->name map. Cached for 5 minutes."""
    global _org_cache
    now = time.time()
    if _org_cache["data"] and (now - _org_cache["ts"]) < _ORG_CACHE_TTL:
        return jsonify(_org_cache["data"])

    client = get_anthropic_client()
    if not client:
        return jsonify({})

    try:
        result = client.list_organizations()
        orgs = result if isinstance(result, list) else result.get("data", [])
        name_map = {}
        for org in orgs:
            oid = org.get("id", "")
            uuid = org.get("uuid", "")
            name = org.get("name", oid)
            if oid:
                name_map[oid] = name
            if uuid:
                name_map[uuid] = name
        _org_cache = {"data": name_map, "ts": now}
        return jsonify(name_map)
    except Exception:
        return jsonify({})


@activities_bp.route("/api/chat-messages/<chat_id>")
@login_required
def api_chat_messages(chat_id):
    """Return chat messages for a given chat ID."""
    client = get_anthropic_client()
    if not client:
        return jsonify({"error": "Not configured", "messages": []})

    try:
        result = client.get_chat_messages(chat_id)
        if isinstance(result, dict):
            messages = result.get("chat_messages") or result.get("data") or []
        else:
            messages = result or []
        return jsonify({"messages": messages})
    except Exception as e:
        return jsonify({"error": str(e), "messages": []})


@activities_bp.route("/api/users")
@login_required
def api_users():
    """Return a lightweight user list for the actor filter dropdown."""
    client = get_anthropic_client()
    if not client:
        return jsonify({"users": []})

    try:
        result = client.list_organizations()
        orgs = result if isinstance(result, list) else result.get("data", [])
    except Exception:
        return jsonify({"users": []})

    users = []
    seen = set()
    for org in orgs:
        org_uuid = org.get("uuid") or org.get("id") or ""
        if not org_uuid:
            continue
        try:
            result = client.list_organization_users(org_uuid)
            data = result.get("data", []) if isinstance(result, dict) else (result or [])
            for u in data:
                uid = u.get("user_id") or u.get("id") or ""
                if uid and uid not in seen:
                    seen.add(uid)
                    users.append({
                        "id": uid,
                        "name": u.get("name") or "",
                        "email": u.get("email") or u.get("email_address") or "",
                    })
        except Exception:
            continue

    users.sort(key=lambda u: (u["name"] or u["email"] or u["id"]).lower())
    return jsonify({"users": users})


@activities_bp.route("/api/user-profile/<path:email>")
@login_required
def api_user_profile(email):
    """Return Entra ID profile data for a user email, proxied via Graph API."""
    gc = get_graph_client()
    if not gc:
        return jsonify({"available": False, "reason": "Graph not configured"})
    try:
        profile = gc.get_user_profile(email)
        return jsonify(profile)
    except Exception as e:
        return jsonify({"available": False, "error": str(e)})


@activities_bp.route("/geolocate/<ip>")
@login_required
def geolocate(ip):
    """Proxy IP geolocation to avoid CORS issues."""
    try:
        resp = http_requests.get(
            f"http://ip-api.com/json/{ip}",
            params={"fields": "status,message,country,regionName,city,lat,lon,isp,org,as,timezone"},
            timeout=5)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"status": "fail", "message": str(e)})


@activities_bp.route("/files/<file_id>/preview")
@login_required
def preview_file(file_id):
    """Serve file content inline for preview (images, PDF, text)."""
    client = get_anthropic_client()
    if not client:
        flash("Anthropic API not configured.", "danger")
        return redirect(url_for("activities.index"))

    try:
        content, filename, content_type = client.download_file(file_id)
    except Exception as e:
        return Response(f"Failed to load file: {e}", status=500, mimetype="text/plain")

    return Response(
        content,
        mimetype=content_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'}
    )


@activities_bp.route("/files/<file_id>/download")
@login_required
def download_file(file_id):
    """Serve file content as a download attachment."""
    client = get_anthropic_client()
    if not client:
        flash("Anthropic API not configured.", "danger")
        return redirect(url_for("activities.index"))

    try:
        content, filename, content_type = client.download_file(file_id)
    except Exception as e:
        flash(f"Failed to download file: {e}", "danger")
        return redirect(request.referrer or url_for("activities.index"))

    return Response(
        content,
        mimetype=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@activities_bp.route("/files/download-all", methods=["POST"])
@login_required
def download_all_files():
    """Download multiple files as a zip, or a single file directly."""
    client = get_anthropic_client()
    if not client:
        return Response("API not configured", status=500, mimetype="text/plain")

    data = request.get_json(silent=True) or {}
    file_ids = data.get("file_ids", [])
    if not file_ids:
        return Response("No file IDs provided", status=400, mimetype="text/plain")

    files = []
    for fid in file_ids:
        try:
            content, filename, content_type = client.download_file(fid)
            files.append((content, filename, content_type))
        except Exception:
            continue

    if not files:
        return Response("No files could be downloaded", status=404, mimetype="text/plain")

    # Single file: return directly in its original format
    if len(files) == 1:
        content, filename, content_type = files[0]
        return Response(
            content,
            mimetype=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    # Multiple files: zip them
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        seen = {}
        for content, filename, _ in files:
            if filename in seen:
                seen[filename] += 1
                dot = filename.rfind(".")
                if dot > 0:
                    filename = f"{filename[:dot]}_{seen[filename]}{filename[dot:]}"
                else:
                    filename = f"{filename}_{seen[filename]}"
            else:
                seen[filename] = 0
            zf.writestr(filename, content)

    buf.seek(0)
    return Response(
        buf.getvalue(),
        mimetype="application/zip",
        headers={"Content-Disposition": 'attachment; filename="attachments.zip"'}
    )
