"""
Azure Table Storage store for ComplianceUsers and ComplianceRoles.
Follows the same pattern as state_manager.py.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from azure.data.tables import TableServiceClient

logger = logging.getLogger(__name__)

# All 13 defined permission names
ALL_PERMISSIONS = [
    "view_dashboard",
    "view_activities",
    "view_chats",
    "view_chat_content",
    "delete_chats",
    "view_projects",
    "delete_projects",
    "delete_files",
    "view_organizations",
    "manage_settings",
    "manage_sync",
    "manage_users",
    "manage_roles",
]

DEFAULT_ROLES = [
    {
        "id": "readonly",
        "name": "Read Only",
        "description": "View-only access. Cannot delete or modify any data.",
        "permissions": [
            "view_dashboard", "view_activities", "view_chats", "view_chat_content",
            "view_projects", "view_organizations",
        ],
        "is_system": True,
    },
    {
        "id": "compliance_auditor",
        "name": "Compliance Auditor",
        "description": "Full read access including all chat content. No admin or delete capabilities.",
        "permissions": [
            "view_dashboard", "view_activities", "view_chats", "view_chat_content",
            "view_projects", "view_organizations",
        ],
        "is_system": True,
    },
    {
        "id": "sysadmin",
        "name": "SysAdmin",
        "description": "Full system administration. Chat content is obscured for user privacy.",
        "permissions": [
            "view_dashboard", "view_activities", "view_chats",
            "view_projects", "view_organizations",
            "manage_settings", "manage_sync", "manage_users",
        ],
        "is_system": True,
    },
    {
        "id": "super_admin",
        "name": "Super Admin",
        "description": "Unrestricted access to all features and data.",
        "permissions": ALL_PERMISSIONS,
        "is_system": True,
    },
]


def _now():
    return datetime.now(timezone.utc).isoformat()


class UserStore:
    def __init__(self, conn_str):
        svc = TableServiceClient.from_connection_string(conn_str)
        self.users_tbl = svc.create_table_if_not_exists("ComplianceUsers")
        self.roles_tbl = svc.create_table_if_not_exists("ComplianceRoles")
        self._seed_default_roles()

    # ── Role helpers ─────────────────────────────────────────────

    def _seed_default_roles(self):
        """Idempotent: insert default roles if the table is empty."""
        try:
            existing = list(self.roles_tbl.query_entities("PartitionKey eq 'role'"))
            existing_ids = {e["RowKey"] for e in existing}
            for role in DEFAULT_ROLES:
                if role["id"] not in existing_ids:
                    self.roles_tbl.upsert_entity({
                        "PartitionKey": "role",
                        "RowKey": role["id"],
                        "name": role["name"],
                        "description": role["description"],
                        "permissions": json.dumps(role["permissions"]),
                        "entra_app_role_id": "",
                        "is_system": role["is_system"],
                        "created_at": _now(),
                        "updated_at": _now(),
                    })
        except Exception as e:
            logger.warning("Could not seed default roles: %s", e)

    def _row_to_role(self, row):
        perms = row.get("permissions", "[]")
        try:
            perms = json.loads(perms)
        except Exception:
            perms = []
        return {
            "id": row["RowKey"],
            "name": row.get("name", ""),
            "description": row.get("description", ""),
            "permissions": perms,
            "entra_app_role_id": row.get("entra_app_role_id", ""),
            "is_system": row.get("is_system", False),
            "created_at": row.get("created_at", ""),
            "updated_at": row.get("updated_at", ""),
        }

    def list_roles(self):
        try:
            rows = self.roles_tbl.query_entities("PartitionKey eq 'role'")
            return [self._row_to_role(r) for r in rows]
        except Exception as e:
            logger.error("list_roles failed: %s", e)
            return []

    def get_role_by_id(self, role_id):
        try:
            row = self.roles_tbl.get_entity(partition_key="role", row_key=role_id)
            return self._row_to_role(row)
        except Exception:
            return None

    def get_role_by_name(self, name):
        """Case-insensitive match on role name."""
        for role in self.list_roles():
            if role["name"].lower() == name.lower():
                return role
        return None

    def upsert_role(self, role_dict):
        """Create or update a role. role_dict must include 'id'."""
        role_id = role_dict.get("id") or str(uuid.uuid4())
        perms = role_dict.get("permissions", [])
        existing = self.get_role_by_id(role_id)
        self.roles_tbl.upsert_entity({
            "PartitionKey": "role",
            "RowKey": role_id,
            "name": role_dict.get("name", ""),
            "description": role_dict.get("description", ""),
            "permissions": json.dumps(perms),
            "entra_app_role_id": role_dict.get("entra_app_role_id", ""),
            "is_system": role_dict.get("is_system", False),
            "created_at": existing["created_at"] if existing else _now(),
            "updated_at": _now(),
        })
        return role_id

    def delete_role(self, role_id):
        """Delete a role. Will not delete system roles."""
        role = self.get_role_by_id(role_id)
        if not role:
            return False, "Role not found"
        if role.get("is_system"):
            return False, "Cannot delete a built-in system role"
        try:
            self.roles_tbl.delete_entity(partition_key="role", row_key=role_id)
            return True, "Role deleted"
        except Exception as e:
            return False, str(e)

    def get_permissions_for_role(self, role_id):
        role = self.get_role_by_id(role_id)
        if not role:
            return []
        return role.get("permissions", [])

    # ── User helpers ─────────────────────────────────────────────

    def _row_to_user(self, row):
        return {
            "id": row["RowKey"],
            "username": row.get("username", ""),
            "email": row.get("email", ""),
            "display_name": row.get("display_name", ""),
            "password_hash": row.get("password_hash", ""),
            "role_id": row.get("role_id", "readonly"),
            "auth_type": row.get("auth_type", "local"),
            "entra_id": row.get("entra_id", ""),
            "scim_external_id": row.get("scim_external_id", ""),
            "is_active": row.get("is_active", True),
            "created_at": row.get("created_at", ""),
            "updated_at": row.get("updated_at", ""),
        }

    def list_users(self):
        try:
            rows = self.users_tbl.query_entities("PartitionKey eq 'user'")
            return [self._row_to_user(r) for r in rows]
        except Exception as e:
            logger.error("list_users failed: %s", e)
            return []

    def get_user_by_id(self, user_id):
        try:
            row = self.users_tbl.get_entity(partition_key="user", row_key=user_id)
            return self._row_to_user(row)
        except Exception:
            return None

    def _find_user(self, field, value):
        for u in self.list_users():
            if u.get(field, "").lower() == value.lower():
                return u
        return None

    def get_user_by_username(self, username):
        return self._find_user("username", username)

    def get_user_by_email(self, email):
        return self._find_user("email", email)

    def get_user_by_entra_id(self, entra_id):
        return self._find_user("entra_id", entra_id)

    def get_user_by_scim_external_id(self, scim_id):
        return self._find_user("scim_external_id", scim_id)

    def upsert_user(self, user_dict):
        """Create or update a user. Generates a new UUID id if not present."""
        user_id = user_dict.get("id") or str(uuid.uuid4())
        existing = self.get_user_by_id(user_id)
        self.users_tbl.upsert_entity({
            "PartitionKey": "user",
            "RowKey": user_id,
            "username": user_dict.get("username", ""),
            "email": user_dict.get("email", ""),
            "display_name": user_dict.get("display_name", ""),
            "password_hash": user_dict.get("password_hash", ""),
            "role_id": user_dict.get("role_id", "readonly"),
            "auth_type": user_dict.get("auth_type", "local"),
            "entra_id": user_dict.get("entra_id", ""),
            "scim_external_id": user_dict.get("scim_external_id", ""),
            "is_active": user_dict.get("is_active", True),
            "created_at": existing["created_at"] if existing else _now(),
            "updated_at": _now(),
        })
        return user_id

    def delete_user(self, user_id):
        try:
            self.users_tbl.delete_entity(partition_key="user", row_key=user_id)
            return True, "User deleted"
        except Exception as e:
            return False, str(e)
