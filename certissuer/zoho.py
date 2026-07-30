"""Minimal Zoho Learn API client for reading course completions.

Used by the scheduled sync to find learners who have completed a course, so
their certificates can be issued and emailed automatically.

Only the standard library is used for HTTP. Configuration comes from the
environment (see .env.example / docs/ZOHO_SETUP.md):

  ZOHO_ACCOUNTS_DOMAIN  OAuth host for your data center, e.g. accounts.zoho.com
                        (.in / .eu / .com.au / .jp for other DCs).
  ZOHO_API_DOMAIN       Learn API host, e.g. learn.zoho.com (matches your DC).
  ZOHO_CLIENT_ID        OAuth client id.
  ZOHO_CLIENT_SECRET    OAuth client secret.
  ZOHO_REFRESH_TOKEN    OAuth refresh token (long-lived).
  ZOHO_PORTAL_ID        Your Learn portal / org id (sent as the orgId header).
  ZOHO_COURSE_MAP       JSON mapping Zoho course id -> our course key, e.g.
                        {"895000000012345": "GHG"}.

NOTE: Zoho's exact report path and field names vary a little by portal/API
version. `iter_completed_learners` looks across the common field names and, if
it can't find learners, tells you to run `sync_zoho.py --dump` and share the
shape so the mapping can be pinned down. This is intentional — it lets us
validate against your real portal on the first run without guessing blind.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass
class ZohoConfig:
    accounts_domain: str
    api_domain: str
    client_id: str
    client_secret: str
    refresh_token: str
    portal_id: str
    course_map: dict[str, str]

    @classmethod
    def from_env(cls) -> "ZohoConfig":
        required = [
            "ZOHO_CLIENT_ID",
            "ZOHO_CLIENT_SECRET",
            "ZOHO_REFRESH_TOKEN",
            "ZOHO_PORTAL_ID",
            "ZOHO_COURSE_MAP",
        ]
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            raise RuntimeError(
                "Missing Zoho env var(s): " + ", ".join(missing) + " (see docs/ZOHO_SETUP.md)."
            )
        try:
            course_map = json.loads(os.environ["ZOHO_COURSE_MAP"])
            assert isinstance(course_map, dict) and course_map
        except Exception:
            raise RuntimeError(
                'ZOHO_COURSE_MAP must be JSON like {"<zoho_course_id>": "GHG"}.'
            ) from None
        return cls(
            accounts_domain=os.environ.get("ZOHO_ACCOUNTS_DOMAIN", "accounts.zoho.com"),
            api_domain=os.environ.get("ZOHO_API_DOMAIN", "learn.zoho.com"),
            client_id=os.environ["ZOHO_CLIENT_ID"],
            client_secret=os.environ["ZOHO_CLIENT_SECRET"],
            refresh_token=os.environ["ZOHO_REFRESH_TOKEN"],
            portal_id=os.environ["ZOHO_PORTAL_ID"],
            course_map={str(k): str(v) for k, v in course_map.items()},
        )


class ZohoClient:
    def __init__(self, cfg: ZohoConfig):
        self.cfg = cfg
        self._token: str | None = None

    # --- auth ---------------------------------------------------------------
    def access_token(self) -> str:
        if self._token:
            return self._token
        url = f"https://{self.cfg.accounts_domain}/oauth/v2/token"
        data = urllib.parse.urlencode(
            {
                "refresh_token": self.cfg.refresh_token,
                "client_id": self.cfg.client_id,
                "client_secret": self.cfg.client_secret,
                "grant_type": "refresh_token",
            }
        ).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
        token = body.get("access_token")
        if not token:
            raise RuntimeError(f"Zoho token refresh failed: {body}")
        self._token = token
        return token

    # --- requests -----------------------------------------------------------
    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"https://{self.cfg.api_domain}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", f"Zoho-oauthtoken {self.access_token()}")
        req.add_header("orgId", self.cfg.portal_id)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise RuntimeError(f"Zoho API {e.code} on {path}: {detail}") from None

    def fetch_course_report(self, course_id: str) -> dict:
        """Fetch the course report (learners + progress) for a course.

        Path is overridable via ZOHO_REPORT_PATH if your portal differs; the
        default targets the documented course-report endpoint.
        """
        template = os.environ.get(
            "ZOHO_REPORT_PATH", "/api/v1/courses/{course_id}/report"
        )
        return self._get(template.format(course_id=course_id))


# --- completion extraction (defensive across field-name variants) -----------

_NAME_KEYS = ("name", "fullName", "userName", "learnerName", "displayName")
_EMAIL_KEYS = ("email", "emailId", "emailID", "mailId", "learnerEmail")
_STATUS_KEYS = ("status", "progressStatus", "completionStatus", "courseStatus")
_PERCENT_KEYS = ("percentageCompleted", "percentCompleted", "progress", "completion")
_DATE_KEYS = ("completedTime", "completedDate", "completionTime", "completedOn")
_LIST_KEYS = ("learners", "members", "records", "data", "report", "users", "result")


def _first(d: dict, keys) -> str | None:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _is_completed(row: dict) -> bool:
    status = (_first(row, _STATUS_KEYS) or "").strip().lower()
    if status in {"completed", "complete", "finished", "passed"}:
        return True
    pct = _first(row, _PERCENT_KEYS)
    try:
        return pct is not None and float(str(pct).rstrip("%")) >= 100
    except ValueError:
        return False


def _learner_rows(report: dict) -> list[dict]:
    for k in _LIST_KEYS:
        v = report.get(k)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):  # sometimes nested one level
            for kk in _LIST_KEYS:
                if isinstance(v.get(kk), list):
                    return v[kk]
    return []


@dataclass
class Completion:
    name: str
    email: str
    completed_at: str | None  # ISO/date string if Zoho provides one


def iter_completed_learners(report: dict) -> list[Completion]:
    """Return completed learners from a course report, or raise a helpful error
    if the report shape isn't recognized (run sync_zoho.py --dump to inspect)."""
    rows = _learner_rows(report)
    if not rows:
        raise RuntimeError(
            "Could not find a learner list in the Zoho course report. Run "
            "`python sync_zoho.py --dump` and share the JSON shape so the field "
            "mapping in certissuer/zoho.py can be pinned to your portal."
        )
    out: list[Completion] = []
    for row in rows:
        if not isinstance(row, dict) or not _is_completed(row):
            continue
        email = _first(row, _EMAIL_KEYS)
        name = _first(row, _NAME_KEYS)
        if not email or not name:
            continue  # can't issue without both; surfaced in the run summary
        out.append(
            Completion(
                name=str(name).strip(),
                email=str(email).strip(),
                completed_at=_first(row, _DATE_KEYS),
            )
        )
    return out
