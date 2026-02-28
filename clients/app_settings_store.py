"""
Azure Table Storage store for ComplianceAppSettings.
Stores auth toggles, SCIM token, and editable Entra ID credentials.
Follows the same pattern as state_manager.py.
"""
import logging
from datetime import datetime, timezone
from azure.data.tables import TableServiceClient

logger = logging.getLogger(__name__)

_PARTITION = "settings"


def _now():
    return datetime.now(timezone.utc).isoformat()


class AppSettingsStore:
    def __init__(self, conn_str):
        svc = TableServiceClient.from_connection_string(conn_str)
        self.tbl = svc.create_table_if_not_exists("ComplianceAppSettings")

    def get_setting(self, key, default=None):
        try:
            row = self.tbl.get_entity(partition_key=_PARTITION, row_key=key)
            return row.get("Value", default)
        except Exception:
            return default

    def set_setting(self, key, value):
        self.tbl.upsert_entity({
            "PartitionKey": _PARTITION,
            "RowKey": key,
            "Value": str(value) if value is not None else "",
            "UpdatedAt": _now(),
        })

    def delete_setting(self, key):
        try:
            self.tbl.delete_entity(partition_key=_PARTITION, row_key=key)
        except Exception:
            pass

    def get_all_settings(self):
        try:
            rows = self.tbl.query_entities(f"PartitionKey eq '{_PARTITION}'")
            return {r["RowKey"]: r.get("Value", "") for r in rows}
        except Exception as e:
            logger.error("get_all_settings failed: %s", e)
            return {}
