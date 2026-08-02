"""Zoho Learn API client — confirmed endpoints.

Zoho Learn does not expose a reachable "who completed a course" report to the
public API, so completions are detected from the course-completion **email**
Zoho sends the admin (handled via a Power Automate flow → repository_dispatch).
This module's job is the one API call that *does* work reliably: fetch a
course's member roster so we can resolve a learner's email from their name.

Confirmed request shape (India DC example):
    GET https://learn.zoho.in/learn/api/v1/portal/<portal>/course/<courseId>/member
    Authorization: Zoho-oauthtoken <access_token>
  → { "STATUS":"OK", "MEMBERS": { "usersDetails": [ {name, emailId, ...}, ... ] } }

Environment (see docs/ZOHO_SETUP.md):
  ZOHO_ACCOUNTS_DOMAIN  OAuth host, e.g. accounts.zoho.in
  ZOHO_API_DOMAIN       Learn API host, e.g. learn.zoho.in
  ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET / ZOHO_REFRESH_TOKEN
  ZOHO_PORTAL           portal slug, e.g. aa-impact
  ZOHO_COURSE_MAP       JSON mapping the Zoho course *name* (as it appears in the
                        completion email) to our course + its Zoho course id:
                        {"GHG Accounting Course": {"id":"58084000000002174","course":"GHG"}}
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


def normalize(value: str) -> str:
    """Lowercase, collapse internal whitespace, strip — for name/course matching."""
    return " ".join((value or "").split()).strip().lower()


@dataclass(frozen=True)
class CourseTarget:
    zoho_course_id: str
    course: str  # our course key (GHG / Nature / GHG_Nature_Bundle)


@dataclass
class ZohoConfig:
    accounts_domain: str
    api_domain: str
    client_id: str
    client_secret: str
    refresh_token: str
    portal: str
    # normalized Zoho course name -> CourseTarget
    course_map: dict[str, CourseTarget]

    @classmethod
    def from_env(cls) -> "ZohoConfig":
        required = [
            "ZOHO_CLIENT_ID",
            "ZOHO_CLIENT_SECRET",
            "ZOHO_REFRESH_TOKEN",
            "ZOHO_PORTAL",
            "ZOHO_COURSE_MAP",
        ]
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            raise RuntimeError(
                "Missing Zoho env var(s): " + ", ".join(missing) + " (see docs/ZOHO_SETUP.md)."
            )
        try:
            raw = json.loads(os.environ["ZOHO_COURSE_MAP"])
            assert isinstance(raw, dict) and raw
            course_map = {
                normalize(name): CourseTarget(str(v["id"]), str(v["course"]))
                for name, v in raw.items()
            }
        except Exception:
            raise RuntimeError(
                'ZOHO_COURSE_MAP must be JSON like '
                '{"GHG Accounting Course": {"id":"58084000000002174","course":"GHG"}}.'
            ) from None
        return cls(
            accounts_domain=os.environ.get("ZOHO_ACCOUNTS_DOMAIN", "accounts.zoho.in"),
            api_domain=os.environ.get("ZOHO_API_DOMAIN", "learn.zoho.in"),
            client_id=os.environ["ZOHO_CLIENT_ID"],
            client_secret=os.environ["ZOHO_CLIENT_SECRET"],
            refresh_token=os.environ["ZOHO_REFRESH_TOKEN"],
            portal=os.environ["ZOHO_PORTAL"],
            course_map=course_map,
        )

    def target_for_course_name(self, course_name: str) -> CourseTarget | None:
        return self.course_map.get(normalize(course_name))

    def zoho_course_id_for_key(self, course_key: str) -> str | None:
        """Reverse lookup: our course key (GHG / ...) -> Zoho course id."""
        for target in self.course_map.values():
            if target.course == course_key:
                return target.zoho_course_id
        return None


class ZohoClient:
    def __init__(self, cfg: ZohoConfig):
        self.cfg = cfg
        self._token: str | None = None

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
        with urllib.request.urlopen(
            urllib.request.Request(url, data=data, method="POST"), timeout=30
        ) as resp:
            body = json.loads(resp.read().decode())
        token = body.get("access_token")
        if not token:
            raise RuntimeError(f"Zoho token refresh failed: {body}")
        self._token = token
        return token

    def course_members(self, course_id: str) -> list[dict]:
        """Return the course roster (each has name, emailId, ...)."""
        url = (
            f"https://{self.cfg.api_domain}/learn/api/v1/portal/"
            f"{self.cfg.portal}/course/{course_id}/member"
        )
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", f"Zoho-oauthtoken {self.access_token()}")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise RuntimeError(f"Zoho API {e.code} fetching members: {detail}") from None
        return (body.get("MEMBERS") or {}).get("usersDetails") or []

    def resolve_email(self, course_id: str, learner_name: str) -> str | None:
        """Find a learner's email by (normalized) name in the course roster.

        Returns None if there is no unique match (caller should log/skip).
        """
        target = normalize(learner_name)
        matches = [
            u for u in self.course_members(course_id) if normalize(u.get("name", "")) == target
        ]
        if len(matches) == 1:
            return (matches[0].get("emailId") or "").strip() or None
        return None

    def find_member(self, course_id: str, email: str) -> dict | None:
        """Return the roster entry whose emailId matches ``email`` (case-insensitive)."""
        target = (email or "").strip().lower()
        if not target:
            return None
        for u in self.course_members(course_id):
            if (u.get("emailId") or "").strip().lower() == target:
                return u
        return None

    @staticmethod
    def _member_zuid(member: dict) -> str | None:
        for key in ("id", "zuid", "userId", "zsoid"):
            val = member.get(key)
            if val:
                return str(val)
        return None

    def enroll_member(
        self, course_id: str, user_ids: list[str], role: str = "MEMBER"
    ) -> dict:
        """Add existing portal users (by Zuid) to a course.

        Zoho Learn's add-members API takes **Zuids**, not emails — so a
        brand-new buyer who has never signed in to Zoho can't be enrolled this
        way. Resolve a Zuid via :meth:`find_member` first; for anyone not yet in
        the portal, fall back to the course sign-up link (the welcome email).
        Requires the ``ZohoLearn.course.UPDATE`` scope on the refresh token.
        """
        url = (
            f"https://{self.cfg.api_domain}/learn/api/v1/portal/"
            f"{self.cfg.portal}/course/{course_id}/member"
        )
        payload = json.dumps(
            {"userIds": [str(u) for u in user_ids], "role": role}
        ).encode()
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Authorization", f"Zoho-oauthtoken {self.access_token()}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise RuntimeError(f"Zoho API {e.code} adding members: {detail}") from None

    def try_enroll_by_email(self, course_id: str, email: str) -> str:
        """Best-effort enrol an existing portal user by email.

        Returns one of: ``"already_member"`` (already on the course),
        ``"enrolled"`` (found their Zuid and added them), or ``"invite_needed"``
        (not a portal user yet — deliver the course sign-up link by email
        instead). Never raises for the ordinary "not a member yet" case.
        """
        member = self.find_member(course_id, email)
        if member:
            status = str(member.get("learnerCourseStatus") or member.get("status") or "")
            # Anyone already on the roster is effectively enrolled.
            return "already_member"
        # Not on this course's roster. We could only add them if they already
        # have a Zuid in the portal, which find_member (course-scoped) can't
        # tell us — so hand off to the email sign-up link.
        return "invite_needed"


_SUBJECT_RE = re.compile(r"^\s*(?P<name>.+?)\s+has completed course\s+(?P<course>.+?)\.?\s*$")


def parse_completion_subject(subject: str) -> tuple[str, str] | None:
    """Parse '<Name> has completed course <Course>.' -> (name, course_name)."""
    m = _SUBJECT_RE.match(subject or "")
    if not m:
        return None
    return m.group("name").strip(), m.group("course").strip()
