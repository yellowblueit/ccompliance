"""
Azure Table Storage store for ComplianceGroups (SCIM Groups / role mapping).
Follows the same pattern as state_manager.py.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from azure.data.tables import TableServiceClient

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc).isoformat()


class GroupStore:
    def __init__(self, conn_str):
        svc = TableServiceClient.from_connection_string(conn_str)
        self.tbl = svc.create_table_if_not_exists("ComplianceGroups")

    def _row_to_group(self, row):
        members = row.get("members", "[]")
        try:
            members = json.loads(members)
        except Exception:
            members = []
        return {
            "id": row["RowKey"],
            "display_name": row.get("display_name", ""),
            "role_id": row.get("role_id", ""),
            "scim_external_id": row.get("scim_external_id", ""),
            "members": members,
            "created_at": row.get("created_at", ""),
            "updated_at": row.get("updated_at", ""),
        }

    def list_groups(self):
        try:
            rows = self.tbl.query_entities("PartitionKey eq 'group'")
            return [self._row_to_group(r) for r in rows]
        except Exception as e:
            logger.error("list_groups failed: %s", e)
            return []

    def get_group_by_id(self, group_id):
        try:
            row = self.tbl.get_entity(partition_key="group", row_key=group_id)
            return self._row_to_group(row)
        except Exception:
            return None

    def get_group_by_scim_external_id(self, ext_id):
        for g in self.list_groups():
            if g.get("scim_external_id") == ext_id:
                return g
        return None

    def get_group_by_name(self, name):
        for g in self.list_groups():
            if g.get("display_name", "").lower() == name.lower():
                return g
        return None

    def upsert_group(self, group_dict):
        """Create or update a group. Returns group_id."""
        group_id = group_dict.get("id") or str(uuid.uuid4())
        existing = self.get_group_by_id(group_id)
        members = group_dict.get("members", [])
        self.tbl.upsert_entity({
            "PartitionKey": "group",
            "RowKey": group_id,
            "display_name": group_dict.get("display_name", ""),
            "role_id": group_dict.get("role_id", ""),
            "scim_external_id": group_dict.get("scim_external_id", ""),
            "members": json.dumps(members),
            "created_at": existing["created_at"] if existing else _now(),
            "updated_at": _now(),
        })
        return group_id

    def delete_group(self, group_id):
        try:
            self.tbl.delete_entity(partition_key="group", row_key=group_id)
            return True, "Group deleted"
        except Exception as e:
            return False, str(e)
