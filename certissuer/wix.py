"""Wix Forms submissions client — capture paid course buyers.

The AA Impact site (aaimpactinc.com) takes payment through a Wix **Forms &
Payments** form named "Payment" — *not* Pricing Plans or Wix Stores — so the
buyer's name + email are captured as form-submission field values. Wix marks a
submission ``CONFIRMED`` once the payment succeeds. This module lists those
confirmed submissions via the Forms REST API so the enrolment pipeline can
auto-provision the buyer (see ``poll_wix_submissions.py``). It replaces the
never-firing Pricing-Plans Velo event the repo originally documented.

Confirmed request shape (account-level API key; site id header required because
API keys are account-scoped):

    POST https://www.wixapis.com/forms/v4/submissions/namespace/query
    Authorization: <WIX_API_KEY>
    wix-site-id: <WIX_SITE_ID>
    {
      "query": {
        "filter": {
          "namespace": "wix.form_app.form",
          "formId":    {"$in": ["a2b557bc-..."]},
          "status":    {"$eq": "CONFIRMED"}
        },
        "cursorPaging": {"limit": 100}
      }
    }
  -> { "submissions": [
         {"id": ..., "formId": ..., "status": "CONFIRMED",
          "submissions": {"email_076a": "...", "first_name_e962": "...", ...}, ...}
       ],
       "metadata": {"cursors": {"next": ...}, "hasNext": bool} }

Environment (see docs/WIX_ENROLMENT_SETUP.md):
  WIX_API_KEY          account API key with the Forms "Read Submissions" scope
  WIX_SITE_ID          site id (default is the AA Impact site)
  WIX_FORM_COURSE_MAP  JSON mapping each *paid* form id -> our course key, e.g.
                       {"a2b557bc-9d1e-4125-bf90-9224c5c07978": "GHG"}
  WIX_POLL_LOOKBACK_DAYS  optional; only look at submissions this recent (0/unset
                       = no time filter). Idempotency lives downstream, so this
                       is purely a volume guard.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

WIX_NAMESPACE = "wix.form_app.form"
QUERY_URL = "https://www.wixapis.com/forms/v4/submissions/namespace/query"

# AA Impact defaults — the "Payment" form sells the GHG course. Override via
# WIX_FORM_COURSE_MAP / WIX_SITE_ID when more paid forms/courses are added.
DEFAULT_SITE_ID = "bc6a0452-5643-4224-a190-e0c157754f82"
DEFAULT_FORM_COURSE_MAP = {"a2b557bc-9d1e-4125-bf90-9224c5c07978": "GHG"}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _extract_email(fields: dict) -> str | None:
    """Pull the buyer's email out of a submission's field-value map.

    Prefers a field keyed like ``email`` (Wix targets look like ``email_076a``);
    falls back to any value that looks like an email address.
    """
    for key, val in fields.items():
        if isinstance(val, str) and key.lower().startswith("email"):
            v = val.strip()
            if _EMAIL_RE.match(v):
                return v
    for val in fields.values():
        if isinstance(val, str) and _EMAIL_RE.match(val.strip()):
            return val.strip()
    return None


def _extract_name(fields: dict) -> str:
    """Build the buyer's name from ``first_name`` + ``last_name`` (Wix targets
    look like ``first_name_e962``), falling back to a single name/full-name
    field. Returns "" if nothing usable is present."""
    first = last = full = ""
    for key, val in fields.items():
        if not isinstance(val, str):
            continue
        k = key.lower()
        v = val.strip()
        if k.startswith("first_name"):
            first = v
        elif k.startswith("last_name"):
            last = v
        elif k in ("name", "full_name") or k.startswith("full_name"):
            full = v
    return (f"{first} {last}".strip() or full).strip()


@dataclass(frozen=True)
class Buyer:
    email: str
    name: str
    course: str
    submission_id: str
    status: str


@dataclass
class WixConfig:
    api_key: str
    site_id: str
    # paid form id -> our course key (GHG / Nature / GHG_Nature_Bundle)
    form_course_map: dict[str, str] = field(default_factory=dict)
    lookback_days: int = 0

    @classmethod
    def from_env(cls) -> "WixConfig":
        api_key = (os.environ.get("WIX_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError(
                "WIX_API_KEY is not set. Create an account API key with the Wix "
                "Forms 'Read Submissions' permission (see docs/WIX_ENROLMENT_SETUP.md)."
            )
        raw_map = (os.environ.get("WIX_FORM_COURSE_MAP") or "").strip()
        if raw_map:
            try:
                parsed = json.loads(raw_map)
                assert isinstance(parsed, dict) and parsed
                form_course_map = {str(k): str(v) for k, v in parsed.items()}
            except Exception:
                raise RuntimeError(
                    'WIX_FORM_COURSE_MAP must be JSON like '
                    '{"a2b557bc-9d1e-4125-bf90-9224c5c07978": "GHG"}.'
                ) from None
        else:
            form_course_map = dict(DEFAULT_FORM_COURSE_MAP)
        try:
            lookback = int(os.environ.get("WIX_POLL_LOOKBACK_DAYS") or "0")
        except ValueError:
            lookback = 0
        return cls(
            api_key=api_key,
            site_id=(os.environ.get("WIX_SITE_ID") or DEFAULT_SITE_ID).strip(),
            form_course_map=form_course_map,
            lookback_days=max(0, lookback),
        )


class WixClient:
    def __init__(self, cfg: WixConfig):
        self.cfg = cfg

    def _post(self, url: str, body: dict) -> dict:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
        req.add_header("Authorization", self.cfg.api_key)
        req.add_header("wix-site-id", self.cfg.site_id)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise RuntimeError(f"Wix API {e.code} querying submissions: {detail}") from None

    def query_confirmed_submissions(self) -> list[dict]:
        """Return CONFIRMED (i.e. paid) submissions for the mapped paid forms."""
        filt: dict = {"namespace": WIX_NAMESPACE, "status": {"$eq": "CONFIRMED"}}
        form_ids = list(self.cfg.form_course_map.keys())
        if form_ids:
            filt["formId"] = {"$in": form_ids}
        if self.cfg.lookback_days:
            from datetime import datetime, timedelta, timezone

            since = datetime.now(timezone.utc) - timedelta(days=self.cfg.lookback_days)
            filt["createdDate"] = {"$gte": since.isoformat()}

        out: list[dict] = []
        cursor: str | None = None
        for _ in range(50):  # safety cap; volume here is tiny
            paging = {"limit": 100}
            if cursor:
                paging["cursor"] = cursor
            body = {
                "query": {
                    "filter": filt,
                    "sort": [{"fieldName": "createdDate", "order": "DESC"}],
                    "cursorPaging": paging,
                }
            }
            resp = self._post(QUERY_URL, body)
            out.extend(resp.get("submissions") or [])
            meta = resp.get("metadata") or {}
            cursor = (meta.get("cursors") or {}).get("next")
            if not cursor or not meta.get("hasNext"):
                break
        return out

    def buyers(self, submissions: list[dict] | None = None) -> list[Buyer]:
        """Resolve confirmed submissions into Buyer records (email, name, course).

        Submissions without a mapped course, a resolvable email, or a CONFIRMED
        status are skipped. Fetches submissions itself when none are passed.
        """
        if submissions is None:
            submissions = self.query_confirmed_submissions()
        buyers: list[Buyer] = []
        for sub in submissions:
            if str(sub.get("status") or "").upper() != "CONFIRMED":
                continue
            course = self.cfg.form_course_map.get(str(sub.get("formId") or ""))
            if not course:
                continue
            fields = sub.get("submissions") or {}
            email = _extract_email(fields)
            if not email:
                continue
            buyers.append(
                Buyer(
                    email=email,
                    name=_extract_name(fields) or email.split("@", 1)[0],
                    course=course,
                    submission_id=str(sub.get("id") or ""),
                    status="CONFIRMED",
                )
            )
        return buyers
