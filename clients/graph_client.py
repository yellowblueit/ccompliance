"""
Microsoft Graph client - extracted from function_app.py (unchanged).
"""
import requests
from datetime import datetime, timezone, timedelta


class GraphClient:
    def __init__(self, tenant_id, client_id, client_secret):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = requests.Session()
        self.session.verify = False
        self.token_expiry = datetime.min.replace(tzinfo=timezone.utc)

    def _ensure_token(self):
        if datetime.now(timezone.utc) < self.token_expiry:
            return
        resp = self.session.post(
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            })
        resp.raise_for_status()
        td = resp.json()
        self.session.headers.update({
            "Authorization": f"Bearer {td['access_token']}",
            "Content-Type": "application/json",
        })
        self.token_expiry = datetime.now(timezone.utc) + timedelta(
            seconds=td.get("expires_in", 3600) - 120)

    def get_or_create_folder(self, mailbox, folder_name, is_hidden=None):
        self._ensure_token()
        url = f"https://graph.microsoft.com/v1.0/users/{mailbox}/mailFolders"
        # Include hidden folders in the search so we find previously hidden ones
        resp = self.session.get(
            url, params={
                "$filter": f"displayName eq '{folder_name}'",
                "includeHiddenFolders": "true",
            })
        resp.raise_for_status()
        folders = resp.json().get("value", [])
        if folders:
            folder_id = folders[0]["id"]
            # Update hidden state if requested and different from current
            if is_hidden is not None and folders[0].get("isHidden") != is_hidden:
                patch_url = f"{url}/{folder_id}"
                self.session.patch(patch_url, json={"isHidden": is_hidden})
            return folder_id
        body = {"displayName": folder_name}
        if is_hidden is not None:
            body["isHidden"] = is_hidden
        resp = self.session.post(url, json=body)
        resp.raise_for_status()
        return resp.json()["id"]

    def get_user_by_email(self, email):
        """Look up a user in Azure AD by email. Returns user dict or None."""
        self._ensure_token()
        resp = self.session.get(
            f"https://graph.microsoft.com/v1.0/users/{email}",
            params={"$select": "id,displayName,mail,accountEnabled,userPrincipalName"})
        if resp.ok:
            return resp.json()
        return None

    def check_users_mailbox_status(self, emails):
        """Check mailbox/account status for a list of emails.
        Returns dict mapping email -> {exists, enabled, display_name}."""
        results = {}
        for email in emails:
            if not email:
                continue
            user = self.get_user_by_email(email)
            if user:
                results[email.lower()] = {
                    "exists": True,
                    "enabled": user.get("accountEnabled", False),
                    "display_name": user.get("displayName", ""),
                    "upn": user.get("userPrincipalName", ""),
                }
            else:
                results[email.lower()] = {
                    "exists": False,
                    "enabled": False,
                    "display_name": "",
                    "upn": "",
                }
        return results

    def get_user_profile(self, email):
        """Return an enriched profile dict for a user, or {'available': False} on failure.

        Fetches:
        - Core profile fields (job title, department, office, phones, address)
        - Manager (display name + title, separate call)
        - Photo (as a base64 data URI, separate call)
        """
        import base64
        self._ensure_token()

        fields = ",".join([
            "id", "displayName", "mail", "userPrincipalName", "accountEnabled",
            "jobTitle", "department", "officeLocation",
            "businessPhones", "mobilePhone",
            "streetAddress", "city", "state", "postalCode", "countryOrRegion",
        ])
        resp = self.session.get(
            f"https://graph.microsoft.com/v1.0/users/{email}",
            params={"$select": fields})
        if not resp.ok:
            return {"available": False}

        profile = resp.json()
        profile["available"] = True

        # Manager
        try:
            mgr_resp = self.session.get(
                f"https://graph.microsoft.com/v1.0/users/{email}/manager",
                params={"$select": "displayName,mail,jobTitle"})
            if mgr_resp.ok:
                mgr = mgr_resp.json()
                profile["manager"] = {
                    "displayName": mgr.get("displayName", ""),
                    "mail": mgr.get("mail", ""),
                    "jobTitle": mgr.get("jobTitle", ""),
                }
        except Exception:
            pass

        # Photo (returns raw image bytes)
        try:
            photo_resp = self.session.get(
                f"https://graph.microsoft.com/v1.0/users/{email}/photo/$value")
            if photo_resp.ok:
                ct = photo_resp.headers.get("Content-Type", "image/jpeg")
                b64 = base64.b64encode(photo_resp.content).decode("ascii")
                profile["photo_data_uri"] = f"data:{ct};base64,{b64}"
        except Exception:
            pass

        return profile

    def create_message(self, mailbox, folder_id, message):
        self._ensure_token()
        resp = self.session.post(
            f"https://graph.microsoft.com/v1.0/users/{mailbox}/mailFolders/{folder_id}/messages",
            json=message)
        resp.raise_for_status()
        return resp.json()
