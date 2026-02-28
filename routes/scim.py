"""
SCIM 2.0 provider for Entra ID user provisioning.
Endpoints: /scim/v2/Users, /scim/v2/Groups, plus discovery endpoints.
Auth: Bearer token validated against ComplianceAppSettings.scim_bearer_token
"""
import re
import logging
from functools import wraps
from flask import Blueprint, request, jsonify, current_app

logger = logging.getLogger(__name__)

scim_bp = Blueprint("scim", __name__)

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
SCIM_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"


# ── Helpers ───────────────────────────────────────────────────────────────────

def scim_error(status, detail):
    return jsonify({
        "schemas": [SCIM_ERROR_SCHEMA],
        "status": str(status),
        "detail": detail,
    }), status


def scim_response(data, status=200):
    resp = jsonify(data)
    resp.headers["Content-Type"] = "application/scim+json"
    return resp, status


def scim_auth_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return scim_error(401, "Bearer token required")
        token = auth_header[7:].strip()
        store = current_app.config.get("APP_SETTINGS_STORE")
        if not store:
            return scim_error(503, "App settings store not configured")
        stored = store.get_setting("scim_bearer_token", "")
        if not stored or token != stored:
            return scim_error(401, "Invalid or missing bearer token")
        return f(*args, **kwargs)
    return decorated


def _base_url():
    return request.host_url.rstrip("/") + "/scim/v2"


def _user_to_scim(user):
    return {
        "schemas": [SCIM_USER_SCHEMA],
        "id": user["id"],
        "externalId": user.get("scim_external_id", ""),
        "userName": user.get("username") or user.get("email", ""),
        "name": {
            "formatted": user.get("display_name", ""),
            "displayName": user.get("display_name", ""),
        },
        "displayName": user.get("display_name", ""),
        "emails": [{"value": user.get("email", ""), "primary": True, "type": "work"}] if user.get("email") else [],
        "active": user.get("is_active", True),
        "roles": [{"value": user.get("role_id", "readonly")}],
        "meta": {
            "resourceType": "User",
            "created": user.get("created_at", ""),
            "lastModified": user.get("updated_at", ""),
            "location": f"{_base_url()}/Users/{user['id']}",
        },
    }


def _group_to_scim(group, user_store=None):
    members = []
    for uid in group.get("members", []):
        entry = {"value": uid}
        if user_store:
            u = user_store.get_user_by_id(uid)
            if u:
                entry["display"] = u.get("display_name") or u.get("username", "")
        members.append(entry)
    return {
        "schemas": [SCIM_GROUP_SCHEMA],
        "id": group["id"],
        "externalId": group.get("scim_external_id", ""),
        "displayName": group.get("display_name", ""),
        "members": members,
        "meta": {
            "resourceType": "Group",
            "created": group.get("created_at", ""),
            "lastModified": group.get("updated_at", ""),
            "location": f"{_base_url()}/Groups/{group['id']}",
        },
    }


def _parse_filter(filter_str):
    """Parse simple SCIM filter: 'attr eq "value"' or 'attr eq value'"""
    if not filter_str:
        return None, None
    m = re.match(r'(\w+)\s+eq\s+"?([^"]+)"?', filter_str.strip(), re.IGNORECASE)
    if m:
        return m.group(1).lower(), m.group(2)
    return None, None


def _apply_patch_user(user, operations, user_store):
    """Apply SCIM PATCH Operations to a user dict."""
    for op in operations:
        op_type = op.get("op", "").lower()
        path = op.get("path", "")
        value = op.get("value")

        if path == "active" or path == "Active":
            if op_type in ("replace", "add"):
                user["is_active"] = bool(value)

        elif path in ("userName", "username"):
            if op_type in ("replace", "add") and value:
                user["username"] = str(value)

        elif path in ("displayName", "name.formatted", "name"):
            if op_type in ("replace", "add") and value:
                if isinstance(value, dict):
                    user["display_name"] = value.get("formatted") or value.get("displayName", "")
                else:
                    user["display_name"] = str(value)

        elif path == "emails" or path.startswith("emails"):
            if op_type in ("replace", "add") and value:
                if isinstance(value, list) and value:
                    user["email"] = value[0].get("value", user["email"])
                elif isinstance(value, dict):
                    user["email"] = value.get("value", user["email"])
                elif isinstance(value, str):
                    user["email"] = value

        elif path == "roles" or path.startswith("roles"):
            if op_type in ("replace", "add") and value:
                if isinstance(value, list) and value:
                    role_val = value[0].get("value", "") if isinstance(value[0], dict) else str(value[0])
                elif isinstance(value, dict):
                    role_val = value.get("value", "")
                else:
                    role_val = str(value)
                # Match by role name or id
                role = user_store.get_role_by_name(role_val) or user_store.get_role_by_id(role_val)
                if role:
                    user["role_id"] = role["id"]

    return user


# ── Discovery ─────────────────────────────────────────────────────────────────

@scim_bp.route("/ServiceProviderConfig", methods=["GET"])
def service_provider_config():
    return scim_response({
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "documentationUri": "",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [{
            "type": "oauthbearertoken",
            "name": "OAuth Bearer Token",
            "description": "Authentication scheme using the OAuth Bearer Token standard",
        }],
        "meta": {
            "resourceType": "ServiceProviderConfig",
            "location": f"{_base_url()}/ServiceProviderConfig",
        },
    })


@scim_bp.route("/Schemas", methods=["GET"])
def schemas():
    return scim_response({
        "schemas": [SCIM_LIST_SCHEMA],
        "totalResults": 2,
        "Resources": [
            {"id": SCIM_USER_SCHEMA, "name": "User"},
            {"id": SCIM_GROUP_SCHEMA, "name": "Group"},
        ],
    })


@scim_bp.route("/ResourceTypes", methods=["GET"])
def resource_types():
    base = _base_url()
    return scim_response({
        "schemas": [SCIM_LIST_SCHEMA],
        "totalResults": 2,
        "Resources": [
            {
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
                "id": "User", "name": "User",
                "endpoint": "/Users",
                "schema": SCIM_USER_SCHEMA,
                "meta": {"resourceType": "ResourceType", "location": f"{base}/ResourceTypes/User"},
            },
            {
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
                "id": "Group", "name": "Group",
                "endpoint": "/Groups",
                "schema": SCIM_GROUP_SCHEMA,
                "meta": {"resourceType": "ResourceType", "location": f"{base}/ResourceTypes/Group"},
            },
        ],
    })


# ── Users ─────────────────────────────────────────────────────────────────────

@scim_bp.route("/Users", methods=["GET"])
@scim_auth_required
def list_users():
    user_store = current_app.config.get("USER_STORE")
    if not user_store:
        return scim_error(503, "User store not configured")

    filter_str = request.args.get("filter", "")
    start_index = max(1, int(request.args.get("startIndex", 1)))
    count = min(200, int(request.args.get("count", 100)))

    all_users = user_store.list_users()

    if filter_str:
        attr, val = _parse_filter(filter_str)
        if attr == "username":
            all_users = [u for u in all_users if u.get("username", "").lower() == val.lower()]
        elif attr == "externalid":
            all_users = [u for u in all_users if u.get("scim_external_id", "") == val]
        elif attr == "emails":
            all_users = [u for u in all_users if u.get("email", "").lower() == val.lower()]

    total = len(all_users)
    page = all_users[start_index - 1: start_index - 1 + count]

    return scim_response({
        "schemas": [SCIM_LIST_SCHEMA],
        "totalResults": total,
        "startIndex": start_index,
        "itemsPerPage": len(page),
        "Resources": [_user_to_scim(u) for u in page],
    })


@scim_bp.route("/Users", methods=["POST"])
@scim_auth_required
def create_user():
    user_store = current_app.config.get("USER_STORE")
    if not user_store:
        return scim_error(503, "User store not configured")

    data = request.get_json(force=True)
    if not data:
        return scim_error(400, "Request body required")

    # Extract userName or fallback to primary email
    username = data.get("userName", "")
    emails = data.get("emails", [])
    email = emails[0].get("value", "") if emails else ""
    if not username:
        username = email

    if not username:
        return scim_error(400, "userName is required")

    # Check for duplicate
    if user_store.get_user_by_username(username):
        return scim_error(409, f"User '{username}' already exists")

    external_id = data.get("externalId", "")
    if external_id and user_store.get_user_by_scim_external_id(external_id):
        return scim_error(409, f"User with externalId '{external_id}' already exists")

    name_obj = data.get("name", {})
    display_name = (
        data.get("displayName")
        or name_obj.get("formatted")
        or f"{name_obj.get('givenName', '')} {name_obj.get('familyName', '')}".strip()
        or username
    )

    # Determine role from SCIM roles claim if provided
    role_id = "readonly"
    scim_roles = data.get("roles", [])
    if scim_roles:
        role_val = scim_roles[0].get("value", "") if isinstance(scim_roles[0], dict) else str(scim_roles[0])
        role = user_store.get_role_by_name(role_val) or user_store.get_role_by_id(role_val)
        if role:
            role_id = role["id"]

    active = data.get("active", True)

    user_id = user_store.upsert_user({
        "username": username,
        "email": email,
        "display_name": display_name,
        "password_hash": "",
        "role_id": role_id,
        "auth_type": "scim",
        "scim_external_id": external_id,
        "is_active": active,
    })
    user = user_store.get_user_by_id(user_id)
    return scim_response(_user_to_scim(user), 201)


@scim_bp.route("/Users/<user_id>", methods=["GET"])
@scim_auth_required
def get_user(user_id):
    user_store = current_app.config.get("USER_STORE")
    if not user_store:
        return scim_error(503, "User store not configured")
    user = user_store.get_user_by_id(user_id)
    if not user:
        return scim_error(404, "User not found")
    return scim_response(_user_to_scim(user))


@scim_bp.route("/Users/<user_id>", methods=["PUT"])
@scim_auth_required
def replace_user(user_id):
    user_store = current_app.config.get("USER_STORE")
    if not user_store:
        return scim_error(503, "User store not configured")

    existing = user_store.get_user_by_id(user_id)
    if not existing:
        return scim_error(404, "User not found")

    data = request.get_json(force=True)
    emails = data.get("emails", [])
    email = emails[0].get("value", existing["email"]) if emails else existing["email"]
    name_obj = data.get("name", {})
    display_name = (
        data.get("displayName")
        or name_obj.get("formatted")
        or existing["display_name"]
    )

    role_id = existing["role_id"]
    scim_roles = data.get("roles", [])
    if scim_roles:
        role_val = scim_roles[0].get("value", "") if isinstance(scim_roles[0], dict) else str(scim_roles[0])
        role = user_store.get_role_by_name(role_val) or user_store.get_role_by_id(role_val)
        if role:
            role_id = role["id"]

    existing.update({
        "username": data.get("userName", existing["username"]),
        "email": email,
        "display_name": display_name,
        "role_id": role_id,
        "scim_external_id": data.get("externalId", existing["scim_external_id"]),
        "is_active": data.get("active", existing["is_active"]),
    })
    user_store.upsert_user(existing)
    user = user_store.get_user_by_id(user_id)
    return scim_response(_user_to_scim(user))


@scim_bp.route("/Users/<user_id>", methods=["PATCH"])
@scim_auth_required
def patch_user(user_id):
    user_store = current_app.config.get("USER_STORE")
    if not user_store:
        return scim_error(503, "User store not configured")

    user = user_store.get_user_by_id(user_id)
    if not user:
        return scim_error(404, "User not found")

    data = request.get_json(force=True)
    operations = data.get("Operations", [])
    user = _apply_patch_user(user, operations, user_store)
    user_store.upsert_user(user)
    user = user_store.get_user_by_id(user_id)
    return scim_response(_user_to_scim(user))


@scim_bp.route("/Users/<user_id>", methods=["DELETE"])
@scim_auth_required
def delete_user(user_id):
    user_store = current_app.config.get("USER_STORE")
    if not user_store:
        return scim_error(503, "User store not configured")

    user = user_store.get_user_by_id(user_id)
    if not user:
        return scim_error(404, "User not found")

    # Soft delete: set is_active=False (preserves audit trail)
    user["is_active"] = False
    user_store.upsert_user(user)
    return "", 204


# ── Groups ────────────────────────────────────────────────────────────────────

def _get_group_store():
    conn = current_app.config.get("APP_CONFIG", {}).get("storage_connection_string", "")
    if not conn:
        return None
    try:
        from clients.group_store import GroupStore
        return GroupStore(conn)
    except Exception:
        return None


@scim_bp.route("/Groups", methods=["GET"])
@scim_auth_required
def list_groups():
    group_store = _get_group_store()
    user_store = current_app.config.get("USER_STORE")
    if not group_store:
        return scim_error(503, "Group store not configured")

    filter_str = request.args.get("filter", "")
    start_index = max(1, int(request.args.get("startIndex", 1)))
    count = min(200, int(request.args.get("count", 100)))

    all_groups = group_store.list_groups()

    if filter_str:
        attr, val = _parse_filter(filter_str)
        if attr == "displayname":
            all_groups = [g for g in all_groups if g.get("display_name", "").lower() == val.lower()]
        elif attr == "externalid":
            all_groups = [g for g in all_groups if g.get("scim_external_id", "") == val]

    total = len(all_groups)
    page = all_groups[start_index - 1: start_index - 1 + count]

    return scim_response({
        "schemas": [SCIM_LIST_SCHEMA],
        "totalResults": total,
        "startIndex": start_index,
        "itemsPerPage": len(page),
        "Resources": [_group_to_scim(g, user_store) for g in page],
    })


@scim_bp.route("/Groups", methods=["POST"])
@scim_auth_required
def create_group():
    group_store = _get_group_store()
    user_store = current_app.config.get("USER_STORE")
    if not group_store:
        return scim_error(503, "Group store not configured")

    data = request.get_json(force=True)
    display_name = data.get("displayName", "").strip()
    if not display_name:
        return scim_error(400, "displayName is required")

    external_id = data.get("externalId", "")
    members_raw = data.get("members", [])
    member_ids = [m.get("value", "") for m in members_raw if isinstance(m, dict)]
    member_ids = [m for m in member_ids if m]

    # Try to map group name to a role
    role_id = ""
    if user_store:
        role = user_store.get_role_by_name(display_name)
        if role:
            role_id = role["id"]

    group_id = group_store.upsert_group({
        "display_name": display_name,
        "role_id": role_id,
        "scim_external_id": external_id,
        "members": member_ids,
    })

    # Apply role to all initial members
    if role_id and user_store:
        for uid in member_ids:
            u = user_store.get_user_by_id(uid)
            if u:
                u["role_id"] = role_id
                user_store.upsert_user(u)

    group = group_store.get_group_by_id(group_id)
    return scim_response(_group_to_scim(group, user_store), 201)


@scim_bp.route("/Groups/<group_id>", methods=["GET"])
@scim_auth_required
def get_group(group_id):
    group_store = _get_group_store()
    user_store = current_app.config.get("USER_STORE")
    if not group_store:
        return scim_error(503, "Group store not configured")
    group = group_store.get_group_by_id(group_id)
    if not group:
        return scim_error(404, "Group not found")
    return scim_response(_group_to_scim(group, user_store))


@scim_bp.route("/Groups/<group_id>", methods=["PUT"])
@scim_auth_required
def replace_group(group_id):
    group_store = _get_group_store()
    user_store = current_app.config.get("USER_STORE")
    if not group_store:
        return scim_error(503, "Group store not configured")

    existing = group_store.get_group_by_id(group_id)
    if not existing:
        return scim_error(404, "Group not found")

    data = request.get_json(force=True)
    display_name = data.get("displayName", existing["display_name"])
    members_raw = data.get("members", [])
    member_ids = [m.get("value", "") for m in members_raw if isinstance(m, dict)]
    member_ids = [m for m in member_ids if m]

    role_id = existing["role_id"]
    if user_store:
        role = user_store.get_role_by_name(display_name)
        if role:
            role_id = role["id"]

    existing.update({
        "display_name": display_name,
        "role_id": role_id,
        "scim_external_id": data.get("externalId", existing["scim_external_id"]),
        "members": member_ids,
    })
    group_store.upsert_group(existing)
    group = group_store.get_group_by_id(group_id)
    return scim_response(_group_to_scim(group, user_store))


@scim_bp.route("/Groups/<group_id>", methods=["PATCH"])
@scim_auth_required
def patch_group(group_id):
    group_store = _get_group_store()
    user_store = current_app.config.get("USER_STORE")
    if not group_store:
        return scim_error(503, "Group store not configured")

    group = group_store.get_group_by_id(group_id)
    if not group:
        return scim_error(404, "Group not found")

    data = request.get_json(force=True)
    operations = data.get("Operations", [])
    members = list(group.get("members", []))

    for op in operations:
        op_type = op.get("op", "").lower()
        path = op.get("path", "")
        value = op.get("value")

        if path == "members" or path.startswith("members"):
            if op_type == "add":
                new_members = value if isinstance(value, list) else [value]
                for m in new_members:
                    uid = m.get("value", "") if isinstance(m, dict) else str(m)
                    if uid and uid not in members:
                        members.append(uid)
                        # Assign role to added user
                        if group.get("role_id") and user_store:
                            u = user_store.get_user_by_id(uid)
                            if u:
                                u["role_id"] = group["role_id"]
                                user_store.upsert_user(u)
            elif op_type == "remove":
                if value:
                    rem = value if isinstance(value, list) else [value]
                    rem_ids = [m.get("value", "") if isinstance(m, dict) else str(m) for m in rem]
                    members = [m for m in members if m not in rem_ids]
                else:
                    members = []

        elif path == "displayName":
            if op_type in ("replace", "add") and value:
                group["display_name"] = str(value)

    group["members"] = members
    group_store.upsert_group(group)
    group = group_store.get_group_by_id(group_id)
    return scim_response(_group_to_scim(group, user_store))


@scim_bp.route("/Groups/<group_id>", methods=["DELETE"])
@scim_auth_required
def delete_group(group_id):
    group_store = _get_group_store()
    if not group_store:
        return scim_error(503, "Group store not configured")
    group = group_store.get_group_by_id(group_id)
    if not group:
        return scim_error(404, "Group not found")
    ok, msg = group_store.delete_group(group_id)
    if not ok:
        return scim_error(400, msg)
    return "", 204
