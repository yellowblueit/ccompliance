from flask import Blueprint, render_template, request, session
from routes import login_required, get_anthropic_client

organizations_bp = Blueprint("organizations", __name__)


@organizations_bp.route("/")
@login_required
def index():
    client = get_anthropic_client()
    if not client:
        return render_template("organizations/list.html", error="Anthropic API not configured. Go to Settings.",
                               organizations=[], user=session.get("user", {}))

    try:
        result = client.list_organizations()
        orgs = result if isinstance(result, list) else result.get("data", [])
    except Exception as e:
        return render_template("organizations/list.html", error=str(e),
                               organizations=[], user=session.get("user", {}))

    return render_template("organizations/list.html",
                           organizations=orgs, user=session.get("user", {}))


@organizations_bp.route("/<org_uuid>/users")
@login_required
def users(org_uuid):
    client = get_anthropic_client()
    if not client:
        return render_template("organizations/users.html", error="Anthropic API not configured.",
                               users=[], org_uuid=org_uuid, user=session.get("user", {}),
                               has_more=False, first_id=None, last_id=None,
                               filters=request.args)

    limit = request.args.get("limit", 50, type=int)
    after_id = request.args.get("after_id", "")
    before_id = request.args.get("before_id", "")

    kwargs = {"limit": limit}
    if after_id:
        kwargs["after_id"] = after_id
    if before_id:
        kwargs["before_id"] = before_id

    try:
        result = client.list_organization_users(org_uuid, **kwargs)
        org_users = result.get("data", []) if isinstance(result, dict) else result
        has_more = result.get("has_more", False) if isinstance(result, dict) else False
        first_id = result.get("first_id") if isinstance(result, dict) else None
        last_id = result.get("last_id") if isinstance(result, dict) else None
    except Exception as e:
        return render_template("organizations/users.html", error=str(e),
                               users=[], org_uuid=org_uuid, user=session.get("user", {}),
                               has_more=False, first_id=None, last_id=None,
                               filters=request.args)

    return render_template("organizations/users.html",
                           users=org_users, org_uuid=org_uuid,
                           has_more=has_more, first_id=first_id, last_id=last_id,
                           limit=limit, filters=request.args,
                           user=session.get("user", {}))
