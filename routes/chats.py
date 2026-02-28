import json
import time
from flask import Blueprint, render_template, request, session, Response, flash, redirect, url_for, jsonify
from routes import login_required, require_permission, get_anthropic_client

chats_bp = Blueprint("chats", __name__)

# Cached filter options: users (id+email), orgs (id+name), and raw user_id list
_filter_cache = {"users": [], "orgs": [], "user_ids": [], "ts": 0}
_FILTER_CACHE_TTL = 300  # 5 minutes


def _get_filter_options(client):
    """Fetch users (with email) and orgs (with name) for filter dropdowns.
    Also returns the flat user_id list needed by the chats API."""
    global _filter_cache
    now = time.time()
    if _filter_cache["user_ids"] and (now - _filter_cache["ts"]) < _FILTER_CACHE_TTL:
        return _filter_cache

    # Fetch orgs
    orgs = []
    try:
        result = client.list_organizations()
        raw = result if isinstance(result, list) else result.get("data", [])
        for o in raw:
            orgs.append({
                "id": o.get("id") or o.get("uuid") or "",
                "uuid": o.get("uuid") or "",
                "name": o.get("name") or "",
            })
    except Exception:
        pass

    # Fetch users from each org
    users = []
    user_id_set = set()
    for org in orgs:
        org_uuid = org["uuid"] or org["id"]
        if not org_uuid:
            continue
        try:
            result = client.list_organization_users(org_uuid)
            data = result.get("data", []) if isinstance(result, dict) else (result or [])
            for u in data:
                uid = u.get("user_id") or u.get("id") or ""
                if uid and uid not in user_id_set:
                    user_id_set.add(uid)
                    users.append({
                        "id": uid,
                        "email": u.get("email") or u.get("email_address") or "",
                        "name": u.get("name") or "",
                    })
        except Exception:
            continue

    _filter_cache = {
        "users": sorted(users, key=lambda u: (u["email"] or u["id"]).lower()),
        "orgs": sorted(orgs, key=lambda o: (o["name"] or o["id"]).lower()),
        "user_ids": list(user_id_set),
        "ts": now,
    }
    return _filter_cache


@chats_bp.route("/")
@login_required
def index():
    client = get_anthropic_client()
    if not client:
        return render_template("chats/list.html", error="Anthropic API not configured. Go to Settings.",
                               chats=[], user=session.get("user", {}),
                               filters={}, has_more=False, last_id=None, first_id=None,
                               all_users=[], all_orgs=[])

    # Load filter dropdown options (cached)
    filter_data = _get_filter_options(client)
    all_users = filter_data["users"]
    all_orgs = filter_data["orgs"]

    # Parse selected filter values (multi-value from checkboxes)
    selected_user_ids = request.args.getlist("user_ids")
    selected_org_ids = request.args.getlist("organization_ids")
    selected_project_ids = request.args.getlist("project_ids")

    filters = {
        "user_ids": selected_user_ids,
        "organization_ids": selected_org_ids,
        "project_ids": selected_project_ids,
        "created_at_gte": request.args.get("created_at_gte", ""),
        "created_at_lte": request.args.get("created_at_lte", ""),
        "updated_at_gte": request.args.get("updated_at_gte", ""),
        "updated_at_lte": request.args.get("updated_at_lte", ""),
        "after_id": request.args.get("after_id", ""),
        "before_id": request.args.get("before_id", ""),
        "limit": request.args.get("limit", "50"),
    }

    kwargs = {"limit": int(filters["limit"] or 50)}
    if selected_user_ids:
        kwargs["user_ids"] = selected_user_ids
    if selected_org_ids:
        kwargs["organization_ids"] = selected_org_ids
    if selected_project_ids:
        kwargs["project_ids"] = selected_project_ids
    if filters["created_at_gte"]:
        kwargs["created_at_gte"] = filters["created_at_gte"]
    if filters["created_at_lte"]:
        kwargs["created_at_lte"] = filters["created_at_lte"]
    if filters["updated_at_gte"]:
        kwargs["updated_at_gte"] = filters["updated_at_gte"]
    if filters["updated_at_lte"]:
        kwargs["updated_at_lte"] = filters["updated_at_lte"]
    if filters["after_id"]:
        kwargs["after_id"] = filters["after_id"]
    if filters["before_id"]:
        kwargs["before_id"] = filters["before_id"]

    # The chats API requires user_ids[] — use all org users if not specified
    if "user_ids" not in kwargs:
        if filter_data["user_ids"]:
            kwargs["user_ids"] = filter_data["user_ids"]
        else:
            return render_template("chats/list.html",
                                   error="The Chats API requires user_ids. "
                                         "Could not auto-detect users from your organizations.",
                                   chats=[], user=session.get("user", {}),
                                   filters=filters, has_more=False, last_id=None, first_id=None,
                                   all_users=all_users, all_orgs=all_orgs)

    # The API limits user_ids[] to 10 per request — batch and merge if needed
    try:
        user_ids = kwargs.pop("user_ids")
        limit = kwargs.get("limit", 50)

        if len(user_ids) <= 10:
            result = client.list_chats(user_ids=user_ids, **kwargs)
            chats = result.get("data", [])
            has_more = result.get("has_more", False)
            last_id = result.get("last_id")
            first_id = result.get("first_id")
        else:
            # Batch into groups of 10, merge results
            all_chats = []
            has_more = False
            for i in range(0, len(user_ids), 10):
                batch = user_ids[i:i + 10]
                result = client.list_chats(user_ids=batch, **kwargs)
                all_chats.extend(result.get("data", []))
                if result.get("has_more"):
                    has_more = True

            # De-duplicate by chat ID
            seen = set()
            chats = []
            for c in all_chats:
                cid = c.get("id")
                if cid and cid not in seen:
                    seen.add(cid)
                    chats.append(c)

            # Sort by created_at ascending (API default) and trim to limit
            chats.sort(key=lambda c: c.get("created_at", ""))
            if len(chats) > limit:
                chats = chats[:limit]
                has_more = True

            first_id = chats[0].get("id") if chats else None
            last_id = chats[-1].get("id") if chats else None

    except Exception as e:
        return render_template("chats/list.html", error=str(e),
                               chats=[], user=session.get("user", {}),
                               filters=filters, has_more=False, last_id=None, first_id=None,
                               all_users=all_users, all_orgs=all_orgs)

    return render_template("chats/list.html",
                           chats=chats, filters=filters,
                           has_more=has_more, last_id=last_id, first_id=first_id,
                           user=session.get("user", {}),
                           all_users=all_users, all_orgs=all_orgs)


@chats_bp.route("/api/projects")
@login_required
def api_projects():
    """Return project list for the filter dropdown (loaded async)."""
    client = get_anthropic_client()
    if not client:
        return jsonify([])

    filter_data = _get_filter_options(client)
    user_ids = filter_data["user_ids"]
    if not user_ids:
        return jsonify([])

    projects = []
    seen = set()
    for i in range(0, len(user_ids), 10):
        batch = user_ids[i:i + 10]
        try:
            result = client.list_projects(user_ids=batch, limit=100)
            for p in result.get("data", []):
                pid = p.get("id", "")
                if pid and pid not in seen:
                    seen.add(pid)
                    projects.append({"id": pid, "name": p.get("name") or pid})
        except Exception:
            continue

    projects.sort(key=lambda p: (p["name"] or p["id"]).lower())
    return jsonify(projects)


@chats_bp.route("/<chat_id>")
@login_required
def detail(chat_id):
    client = get_anthropic_client()
    if not client:
        return render_template("chats/detail.html", error="Anthropic API not configured.",
                               chat={}, messages=[], chat_json="{}", user=session.get("user", {}))

    messages = []
    error = None
    chat = {"id": chat_id}

    try:
        result = client.get_chat_messages(chat_id)
        if isinstance(result, dict):
            messages = result.get("chat_messages") or result.get("data") or []
            chat = result
        else:
            messages = result
    except Exception as e:
        error = f"Failed to load messages: {e}"
        chat_data = request.args.get("data")
        if chat_data:
            try:
                chat = json.loads(chat_data)
            except Exception:
                pass

    return render_template("chats/detail.html",
                           chat=chat, messages=messages, error=error,
                           chat_json=json.dumps(chat, indent=2, default=str),
                           user=session.get("user", {}))


@chats_bp.route("/<chat_id>/delete", methods=["POST"])
@login_required
@require_permission("delete_chats")
def delete(chat_id):
    client = get_anthropic_client()
    if not client:
        flash("Anthropic API not configured.", "danger")
        return redirect(url_for("chats.index"))

    try:
        client.delete_chat(chat_id)
        flash(f"Chat {chat_id} deleted successfully.", "success")
    except Exception as e:
        flash(f"Failed to delete chat: {e}", "danger")

    return redirect(url_for("chats.index"))


@chats_bp.route("/files/<file_id>/download")
@login_required
def download_file(file_id):
    client = get_anthropic_client()
    if not client:
        flash("Anthropic API not configured.", "danger")
        return redirect(url_for("chats.index"))

    try:
        content, filename, content_type = client.download_file(file_id)
        return Response(
            content,
            mimetype=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        flash(f"Failed to download file: {e}", "danger")
        return redirect(request.referrer or url_for("chats.index"))


@chats_bp.route("/files/<file_id>/delete", methods=["POST"])
@login_required
@require_permission("delete_files")
def delete_file(file_id):
    client = get_anthropic_client()
    if not client:
        flash("Anthropic API not configured.", "danger")
        return redirect(url_for("chats.index"))

    try:
        client.delete_file(file_id)
        flash(f"File {file_id} deleted successfully.", "success")
    except Exception as e:
        flash(f"Failed to delete file: {e}", "danger")

    return redirect(request.referrer or url_for("chats.index"))
