"""Microsoft Graph client — read the certificate@ mailbox for completion emails.

Since Zoho has no completion API and Power Automate premium isn't available, we
poll the dedicated mailbox (certificate@aaimpactinc.com) via Microsoft Graph on
a schedule and act on the "<Learner> has completed course <Course>." emails Zoho
sends there.

Delegated auth with a long-lived refresh token (minted once via device-code
login as certificate@ — see scripts/ms_device_login.py). Only that mailbox's
mail is accessible (least privilege). Standard library only.

Environment (see docs/MS_GRAPH_SETUP.md):
  MS_TENANT_ID       Azure AD directory (tenant) id
  MS_CLIENT_ID       app registration (client) id
  MS_REFRESH_TOKEN   refresh token for certificate@ (from device-code login)
  MS_CLIENT_SECRET   optional — only if you registered a confidential client
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPE = "https://graph.microsoft.com/Mail.Read offline_access"


@dataclass
class MSGraphConfig:
    tenant_id: str
    client_id: str
    refresh_token: str
    client_secret: str | None = None

    @classmethod
    def from_env(cls) -> "MSGraphConfig":
        required = ["MS_TENANT_ID", "MS_CLIENT_ID", "MS_REFRESH_TOKEN"]
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            raise RuntimeError(
                "Missing Microsoft Graph env var(s): "
                + ", ".join(missing)
                + " (see docs/MS_GRAPH_SETUP.md)."
            )
        return cls(
            tenant_id=os.environ["MS_TENANT_ID"],
            client_id=os.environ["MS_CLIENT_ID"],
            refresh_token=os.environ["MS_REFRESH_TOKEN"],
            client_secret=os.environ.get("MS_CLIENT_SECRET") or None,
        )


class MSGraphClient:
    def __init__(self, cfg: MSGraphConfig):
        self.cfg = cfg
        self._token: str | None = None

    def access_token(self) -> str:
        if self._token:
            return self._token
        url = f"https://login.microsoftonline.com/{self.cfg.tenant_id}/oauth2/v2.0/token"
        form = {
            "client_id": self.cfg.client_id,
            "grant_type": "refresh_token",
            "refresh_token": self.cfg.refresh_token,
            "scope": SCOPE,
        }
        if self.cfg.client_secret:
            form["client_secret"] = self.cfg.client_secret
        data = urllib.parse.urlencode(form).encode()
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, data=data, method="POST"), timeout=30
            ) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise RuntimeError(f"MS token refresh failed ({e.code}): {detail}") from None
        token = body.get("access_token")
        if not token:
            raise RuntimeError(f"MS token refresh returned no access_token: {body}")
        self._token = token
        return token

    def completion_subjects(
        self,
        sender: str,
        subject_contains: str,
        lookback_hours: int,
    ) -> list[str]:
        """Return subjects of recent messages from ``sender`` whose subject
        contains ``subject_contains`` (case-insensitive), within the lookback
        window."""
        since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        flt = (
            f"receivedDateTime ge {since} and "
            f"from/emailAddress/address eq '{sender}'"
        )
        params = urllib.parse.urlencode(
            {
                "$filter": flt,
                "$select": "subject,receivedDateTime,from",
                "$orderby": "receivedDateTime desc",
                "$top": "50",
            }
        )
        url = f"{GRAPH}/me/mailFolders/Inbox/messages?{params}"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", f"Bearer {self.access_token()}")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise RuntimeError(f"Graph messages query failed ({e.code}): {detail}") from None
        needle = subject_contains.lower()
        return [
            m["subject"]
            for m in body.get("value", [])
            if m.get("subject") and needle in m["subject"].lower()
        ]
