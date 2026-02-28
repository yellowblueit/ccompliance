"""
Local user management API — used by the Settings > Users & Roles tab.
All routes return JSON and require manage_users permission.
"""
import uuid
import logging
from flask import Blueprint, request, jsonify, current_app
from werkzeug.security import generate_password_hash
from routes import login_required, require_permission
from clients.user_store import ALL_PERMISSIONS

logger = logging.getLogger(__name__)

users_bp = Blueprint("users", __name__)


def _store():
    return current_app.config.get("USER_STORE")


@users_bp.route("/", methods=["GET"])
@login_required
@require_permission("manage_users")
def list_users():
    store = _store()
    if not store:
        return jsonify({"error": "User store not configured"}), 503
    users = store.list_users()
    # Never return password hashes to the frontend
    for u in users:
        u.pop("password_hash", None)
    return jsonify(users)


@users_bp.route("/", methods=["POST"])
@login_required
@require_permission("manage_users")
def create_user():
    store = _store()
    if not store:
        return jsonify({"error": "User store not configured"}), 503

    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    if not username:
        return jsonify({"error": "username is required"}), 400

    if store.get_user_by_username(username):
        return jsonify({"error": f"Username '{username}' already exists"}), 409

    password = data.get("password", "")
    password_hash = generate_password_hash(password) if password else ""

    user_id = store.upsert_user({
        "username": username,
        "email": data.get("email", ""),
        "display_name": data.get("display_name", username),
        "password_hash": password_hash,
        "role_id": data.get("role_id", "readonly"),
        "auth_type": "local",
        "is_active": True,
    })
    user = store.get_user_by_id(user_id)
    user.pop("password_hash", None)
    return jsonify(user), 201


@users_bp.route("/<user_id>", methods=["GET"])
@login_required
@require_permission("manage_users")
def get_user(user_id):
    store = _store()
    if not store:
        return jsonify({"error": "User store not configured"}), 503
    user = store.get_user_by_id(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    user.pop("password_hash", None)
    return jsonify(user)


@users_bp.route("/<user_id>", methods=["PUT"])
@login_required
@require_permission("manage_users")
def update_user(user_id):
    store = _store()
    if not store:
        return jsonify({"error": "User store not configured"}), 503
    existing = store.get_user_by_id(user_id)
    if not existing:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(force=True)
    existing.update({
        "email": data.get("email", existing["email"]),
        "display_name": data.get("display_name", existing["display_name"]),
        "role_id": data.get("role_id", existing["role_id"]),
        "is_active": data.get("is_active", existing["is_active"]),
    })
    store.upsert_user(existing)
    existing.pop("password_hash", None)
    return jsonify(existing)


@users_bp.route("/<user_id>", methods=["DELETE"])
@login_required
@require_permission("manage_users")
def delete_user(user_id):
    store = _store()
    if not store:
        return jsonify({"error": "User store not configured"}), 503
    ok, msg = store.delete_user(user_id)
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})


@users_bp.route("/<user_id>/reset-password", methods=["POST"])
@login_required
@require_permission("manage_users")
def reset_password(user_id):
    store = _store()
    if not store:
        return jsonify({"error": "User store not configured"}), 503
    user = store.get_user_by_id(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(force=True)
    password = data.get("password", "")
    if not password or len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    user["password_hash"] = generate_password_hash(password)
    store.upsert_user(user)
    return jsonify({"message": "Password updated"})


@users_bp.route("/permissions", methods=["GET"])
@login_required
@require_permission("manage_roles")
def list_permissions():
    """Return the full list of available permission names."""
    return jsonify(ALL_PERMISSIONS)
