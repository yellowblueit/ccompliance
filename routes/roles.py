"""
Role management API — used by the Settings > Users & Roles tab.
All routes return JSON and require manage_roles permission.
"""
import logging
from flask import Blueprint, request, jsonify, current_app
from routes import login_required, require_permission
from clients.user_store import ALL_PERMISSIONS

logger = logging.getLogger(__name__)

roles_bp = Blueprint("roles", __name__)


def _store():
    return current_app.config.get("USER_STORE")


@roles_bp.route("/", methods=["GET"])
@login_required
@require_permission("manage_roles")
def list_roles():
    store = _store()
    if not store:
        return jsonify({"error": "User store not configured"}), 503
    return jsonify(store.list_roles())


@roles_bp.route("/", methods=["POST"])
@login_required
@require_permission("manage_roles")
def create_role():
    store = _store()
    if not store:
        return jsonify({"error": "User store not configured"}), 503

    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    if store.get_role_by_name(name):
        return jsonify({"error": f"Role '{name}' already exists"}), 409

    # Validate permissions list
    perms = [p for p in data.get("permissions", []) if p in ALL_PERMISSIONS]

    role_id = store.upsert_role({
        "name": name,
        "description": data.get("description", ""),
        "permissions": perms,
        "entra_app_role_id": data.get("entra_app_role_id", ""),
        "is_system": False,
    })
    return jsonify(store.get_role_by_id(role_id)), 201


@roles_bp.route("/<role_id>", methods=["GET"])
@login_required
@require_permission("manage_roles")
def get_role(role_id):
    store = _store()
    if not store:
        return jsonify({"error": "User store not configured"}), 503
    role = store.get_role_by_id(role_id)
    if not role:
        return jsonify({"error": "Role not found"}), 404
    return jsonify(role)


@roles_bp.route("/<role_id>", methods=["PUT"])
@login_required
@require_permission("manage_roles")
def update_role(role_id):
    store = _store()
    if not store:
        return jsonify({"error": "User store not configured"}), 503
    existing = store.get_role_by_id(role_id)
    if not existing:
        return jsonify({"error": "Role not found"}), 404

    data = request.get_json(force=True)
    perms = [p for p in data.get("permissions", existing["permissions"]) if p in ALL_PERMISSIONS]

    existing.update({
        "name": data.get("name", existing["name"]),
        "description": data.get("description", existing["description"]),
        "permissions": perms,
        "entra_app_role_id": data.get("entra_app_role_id", existing.get("entra_app_role_id", "")),
    })
    store.upsert_role(existing)
    return jsonify(store.get_role_by_id(role_id))


@roles_bp.route("/<role_id>", methods=["DELETE"])
@login_required
@require_permission("manage_roles")
def delete_role(role_id):
    store = _store()
    if not store:
        return jsonify({"error": "User store not configured"}), 503
    ok, msg = store.delete_role(role_id)
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})


@roles_bp.route("/permissions", methods=["GET"])
@login_required
@require_permission("manage_roles")
def list_permissions():
    """Return all available permission names."""
    return jsonify(ALL_PERMISSIONS)
