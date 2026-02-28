"""
Extended Anthropic Compliance API client covering all 14 endpoints.
Based on function_app.py AnthropicComplianceClient, extended with full API coverage.
"""
import requests


class AnthropicComplianceClient:
    def __init__(self, api_key, base_url="https://api.anthropic.com"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"x-api-key": api_key})
        self.session.verify = False

    def _get(self, endpoint, params=None):
        resp = self.session.get(f"{self.base_url}{endpoint}", params=params)
        if not resp.ok:
            # Include the API's error message in the exception for debugging
            try:
                body = resp.json()
                err = body.get("error", {})
                msg = err.get("message", "") if isinstance(err, dict) else str(err)
            except Exception:
                msg = resp.text[:500]
            raise Exception(
                f"{resp.status_code} {resp.reason} for {endpoint}: {msg}"
            )
        return resp.json()

    def _delete(self, endpoint):
        resp = self.session.delete(f"{self.base_url}{endpoint}")
        if not resp.ok:
            try:
                body = resp.json()
                err = body.get("error", {})
                msg = err.get("message", "") if isinstance(err, dict) else str(err)
            except Exception:
                msg = resp.text[:500]
            raise Exception(
                f"{resp.status_code} {resp.reason} for {endpoint}: {msg}"
            )
        if resp.status_code == 204:
            return {"status": "deleted"}
        return resp.json() if resp.content else {"status": "deleted"}

    def _get_raw(self, endpoint, stream=False):
        resp = self.session.get(f"{self.base_url}{endpoint}", stream=stream)
        resp.raise_for_status()
        return resp

    # ── Activities ──────────────────────────────────────────────

    def list_activities(self, created_at_gte=None, created_at_gt=None,
                        created_at_lte=None, created_at_lt=None,
                        after_id=None, before_id=None, limit=100,
                        organization_ids=None, actor_ids=None,
                        activity_types=None):
        params = {"limit": limit}
        if created_at_gte:
            params["created_at.gte"] = created_at_gte
        if created_at_gt:
            params["created_at.gt"] = created_at_gt
        if created_at_lte:
            params["created_at.lte"] = created_at_lte
        if created_at_lt:
            params["created_at.lt"] = created_at_lt
        if after_id:
            params["after_id"] = after_id
        if before_id:
            params["before_id"] = before_id
        if organization_ids:
            for oid in organization_ids:
                params.setdefault("organization_ids[]", []).append(oid)
        if actor_ids:
            for aid in actor_ids:
                params.setdefault("actor_ids[]", []).append(aid)
        if activity_types:
            for at in activity_types:
                params.setdefault("activity_types[]", []).append(at)
        return self._get("/v1/compliance/activities", params)

    # ── Organizations & Users ──────────────────────────────────

    def list_organizations(self):
        return self._get("/v1/compliance/organizations")

    def list_organization_users(self, org_uuid, limit=100, after_id=None, before_id=None):
        params = {"limit": limit}
        if after_id:
            params["after_id"] = after_id
        if before_id:
            params["before_id"] = before_id
        return self._get(f"/v1/compliance/organizations/{org_uuid}/users", params)

    # ── Chats ──────────────────────────────────────────────────

    def list_chats(self, user_ids=None, organization_ids=None, project_ids=None,
                   created_at_gte=None, created_at_lte=None,
                   updated_at_gte=None, updated_at_lte=None,
                   after_id=None, before_id=None, limit=100):
        params = {"limit": limit}
        if user_ids:
            for uid in user_ids:
                params.setdefault("user_ids[]", []).append(uid)
        if organization_ids:
            for oid in organization_ids:
                params.setdefault("organization_ids[]", []).append(oid)
        if project_ids:
            for pid in project_ids:
                params.setdefault("project_ids[]", []).append(pid)
        if created_at_gte:
            params["created_at.gte"] = created_at_gte
        if created_at_lte:
            params["created_at.lte"] = created_at_lte
        if updated_at_gte:
            params["updated_at.gte"] = updated_at_gte
        if updated_at_lte:
            params["updated_at.lte"] = updated_at_lte
        if after_id:
            params["after_id"] = after_id
        if before_id:
            params["before_id"] = before_id
        return self._get("/v1/compliance/apps/chats", params)

    def get_chat_messages(self, chat_id):
        return self._get(f"/v1/compliance/apps/chats/{chat_id}/messages")

    def delete_chat(self, chat_id):
        return self._delete(f"/v1/compliance/apps/chats/{chat_id}")

    # ── Chat Files ─────────────────────────────────────────────

    def download_file(self, file_id):
        resp = self._get_raw(f"/v1/compliance/apps/chats/files/{file_id}/content", stream=True)
        cd = resp.headers.get("Content-Disposition", "")
        filename = file_id
        if "filename=" in cd:
            filename = cd.split("filename=")[-1].strip('" ')
        content_type = resp.headers.get("Content-Type", "application/octet-stream")
        return resp.content, filename, content_type

    def delete_file(self, file_id):
        return self._delete(f"/v1/compliance/apps/chats/files/{file_id}")

    # ── Projects ───────────────────────────────────────────────

    def list_projects(self, organization_ids=None, user_ids=None,
                      created_at_gte=None, created_at_lte=None,
                      after_id=None, before_id=None, limit=100):
        params = {"limit": limit}
        if organization_ids:
            for oid in organization_ids:
                params.setdefault("organization_ids[]", []).append(oid)
        if user_ids:
            for uid in user_ids:
                params.setdefault("user_ids[]", []).append(uid)
        if created_at_gte:
            params["created_at.gte"] = created_at_gte
        if created_at_lte:
            params["created_at.lte"] = created_at_lte
        if after_id:
            params["after_id"] = after_id
        if before_id:
            params["before_id"] = before_id
        return self._get("/v1/compliance/apps/projects", params)

    def get_project(self, project_id):
        return self._get(f"/v1/compliance/apps/projects/{project_id}")

    def delete_project(self, project_id):
        return self._delete(f"/v1/compliance/apps/projects/{project_id}")

    def list_project_attachments(self, project_id):
        return self._get(f"/v1/compliance/apps/projects/{project_id}/attachments")

    def get_project_document(self, document_id):
        return self._get(f"/v1/compliance/apps/projects/documents/{document_id}")

    def delete_project_document(self, document_id):
        return self._delete(f"/v1/compliance/apps/projects/documents/{document_id}")
