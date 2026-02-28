import json
import time
from flask import Blueprint, render_template, request, session, flash, redirect, url_for
from routes import login_required, require_permission, get_anthropic_client

projects_bp = Blueprint("projects", __name__)

# App-level org ID cache
_org_cache = {"data": [], "ts": 0}
_ORG_CACHE_TTL = 300  # 5 minutes


def _get_all_org_ids(client):
    """Fetch all organization IDs for project filtering."""
    global _org_cache
    now = time.time()
    if _org_cache["data"] and (now - _org_cache["ts"]) < _ORG_CACHE_TTL:
        return _org_cache["data"]

    try:
        result = client.list_organizations()
        orgs = result if isinstance(result, list) else result.get("data", [])
    except Exception:
        return []

    ids = []
    for o in orgs:
        oid = o.get("id") or o.get("uuid") or ""
        if oid:
            ids.append(oid)

    _org_cache = {"data": ids, "ts": now}
    return ids


@projects_bp.route("/")
@login_required
def index():
    client = get_anthropic_client()
    if not client:
        return render_template("projects/list.html", error="Anthropic API not configured. Go to Settings.",
                               projects=[], user=session.get("user", {}),
                               filters={}, has_more=False, last_id=None, first_id=None)

    filters = {
        "organization_ids": request.args.get("organization_ids", ""),
        "user_ids": request.args.get("user_ids", ""),
        "created_at_gte": request.args.get("created_at_gte", ""),
        "created_at_lte": request.args.get("created_at_lte", ""),
        "after_id": request.args.get("after_id", ""),
        "before_id": request.args.get("before_id", ""),
        "limit": request.args.get("limit", "50"),
    }

    kwargs = {"limit": int(filters["limit"] or 50)}
    if filters["organization_ids"]:
        kwargs["organization_ids"] = [x.strip() for x in filters["organization_ids"].split(",") if x.strip()]
    if filters["user_ids"]:
        kwargs["user_ids"] = [x.strip() for x in filters["user_ids"].split(",") if x.strip()]
    if filters["created_at_gte"]:
        kwargs["created_at_gte"] = filters["created_at_gte"]
    if filters["created_at_lte"]:
        kwargs["created_at_lte"] = filters["created_at_lte"]
    if filters["after_id"]:
        kwargs["after_id"] = filters["after_id"]
    if filters["before_id"]:
        kwargs["before_id"] = filters["before_id"]

    # The projects API requires at least one filter — auto-include all orgs if none given
    if "organization_ids" not in kwargs and "user_ids" not in kwargs:
        org_ids = _get_all_org_ids(client)
        if org_ids:
            kwargs["organization_ids"] = org_ids
        else:
            return render_template("projects/list.html",
                                   error="The Projects API requires at least one filter (organization or user ID). "
                                         "Could not auto-detect organizations. Please enter a filter manually.",
                                   projects=[], user=session.get("user", {}),
                                   filters=filters, has_more=False, last_id=None, first_id=None)

    try:
        result = client.list_projects(**kwargs)
        projects = result.get("data", [])
        has_more = result.get("has_more", False)
        last_id = result.get("last_id")
        first_id = result.get("first_id")
    except Exception as e:
        return render_template("projects/list.html", error=str(e),
                               projects=[], user=session.get("user", {}),
                               filters=filters, has_more=False, last_id=None, first_id=None)

    return render_template("projects/list.html",
                           projects=projects, filters=filters,
                           has_more=has_more, last_id=last_id, first_id=first_id,
                           user=session.get("user", {}))


@projects_bp.route("/<project_id>")
@login_required
def detail(project_id):
    client = get_anthropic_client()
    if not client:
        return render_template("projects/detail.html", error="Anthropic API not configured.",
                               project={}, attachments=[], user=session.get("user", {}))

    error = None
    project = {"id": project_id}
    attachments = []

    try:
        project = client.get_project(project_id)
    except Exception as e:
        error = f"Failed to load project: {e}"

    try:
        result = client.list_project_attachments(project_id)
        attachments = result.get("data", []) if isinstance(result, dict) else result
    except Exception:
        pass  # Attachments are optional

    return render_template("projects/detail.html",
                           project=project, attachments=attachments, error=error,
                           project_json=json.dumps(project, indent=2, default=str),
                           user=session.get("user", {}))


@projects_bp.route("/<project_id>/delete", methods=["POST"])
@login_required
@require_permission("delete_projects")
def delete(project_id):
    client = get_anthropic_client()
    if not client:
        flash("Anthropic API not configured.", "danger")
        return redirect(url_for("projects.index"))

    try:
        client.delete_project(project_id)
        flash(f"Project {project_id} deleted successfully.", "success")
    except Exception as e:
        flash(f"Failed to delete project: {e}", "danger")

    return redirect(url_for("projects.index"))


@projects_bp.route("/documents/<document_id>")
@login_required
def document(document_id):
    client = get_anthropic_client()
    if not client:
        return render_template("projects/document.html", error="Anthropic API not configured.",
                               document={}, user=session.get("user", {}))

    try:
        doc = client.get_project_document(document_id)
    except Exception as e:
        return render_template("projects/document.html", error=str(e),
                               document={}, user=session.get("user", {}))

    return render_template("projects/document.html",
                           document=doc,
                           document_json=json.dumps(doc, indent=2, default=str),
                           user=session.get("user", {}))


@projects_bp.route("/documents/<document_id>/delete", methods=["POST"])
@login_required
@require_permission("delete_projects")
def delete_document(document_id):
    client = get_anthropic_client()
    if not client:
        flash("Anthropic API not configured.", "danger")
        return redirect(url_for("projects.index"))

    try:
        client.delete_project_document(document_id)
        flash(f"Document {document_id} deleted successfully.", "success")
    except Exception as e:
        flash(f"Failed to delete document: {e}", "danger")

    return redirect(request.referrer or url_for("projects.index"))
