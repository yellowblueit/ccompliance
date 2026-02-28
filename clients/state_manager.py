"""
Azure Table Storage state manager - extracted from function_app.py (unchanged).
"""
from datetime import datetime, timezone
from azure.data.tables import TableServiceClient


class StateManager:
    def __init__(self, conn_str):
        svc = TableServiceClient.from_connection_string(conn_str)
        self.cursor_tbl = svc.create_table_if_not_exists("ComplianceSyncState")
        self.chat_tbl = svc.create_table_if_not_exists("ComplianceChatState")

    def get_cursor(self, key):
        try:
            return self.cursor_tbl.get_entity(
                partition_key="cursor", row_key=key).get("Value")
        except Exception:
            return None

    def set_cursor(self, key, value):
        self.cursor_tbl.upsert_entity({
            "PartitionKey": "cursor",
            "RowKey": key,
            "Value": str(value),
            "UpdatedAt": datetime.now(timezone.utc).isoformat(),
        })

    def get_chat_msg_count(self, chat_id):
        try:
            return int(self.chat_tbl.get_entity(
                partition_key="chat", row_key=chat_id).get("MessageCount", 0))
        except Exception:
            return 0

    def set_chat_msg_count(self, chat_id, count):
        self.chat_tbl.upsert_entity({
            "PartitionKey": "chat",
            "RowKey": chat_id,
            "MessageCount": count,
            "UpdatedAt": datetime.now(timezone.utc).isoformat(),
        })
