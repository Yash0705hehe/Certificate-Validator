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


def _iter_member_dicts(body: dict):
    """Yield member dicts from a Zoho members response across its likely shapes.

    The confirmed course-roster shape is ``{"MEMBERS": {"usersDetails": [...]}}``;
    hub-member responses may use that or a flatter ``{"members": [...]}`` form, so
    we scan defensively rather than assume one shape.
    """
    if not isinstance(body, dict):
        return
    members = body.get("MEMBERS")
    if isinstance(members, dict):
        for m in members.get("usersDetails") or []:
            if isinstance(m, dict):
                yield m
    for key in ("members", "data", "usersDetails", "users", "hubMembers"):
        val = body.get(key)
        if isinstance(val, list):
            for m in val:
                if isinstance(m, dict):
                    yield m
        elif isinstance(val, dict):
            for m in val.get("usersDetails") or []:
                if isinstance(m, dict):
                    yield m


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
    portal: str  # hub network URL (e.g. aa-impact) — used for both course and hub calls
    # normalized Zoho course name -> CourseTarget
    course_map: dict[str, CourseTarget]
    # When true, brand-new buyers are provisioned automatically: invited to the
    # hub by email, then (once they accept) auto-enrolled into the course on a
    # later poll. Requires the refresh token to carry ZohoLearn.hubMember.CREATE
    # + ZohoLearn.hubMember.READ. When false, ensure_course_access only reports
    # membership and the caller falls back to the course-access email.
    auto_enroll: bool = False
    # When true, we DON'T send Zoho's own hub invite (whose email content we
    # can't edit). Instead the buyer receives our branded enrolment email (see
    # certissuer.emailer.compose_enrolment) with a link to self-sign-up to the
    # hub; once they do, the reconcile job resolves their Zuid and adds them to
    # the course. Requires "external/self signup" enabled on the Zoho hub.
    self_signup: bool = False

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
            auto_enroll=(os.environ.get("ZOHO_AUTO_ENROLL") or "").strip().lower()
            in ("1", "true", "yes", "on"),
            self_signup=(os.environ.get("ZOHO_SELF_SIGNUP") or "").strip().lower()
            in ("1", "true", "yes", "on"),
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
        the portal, provision them with :meth:`ensure_course_access` (or fall
        back to the course sign-up link in the welcome email).
        Requires the ``ZohoLearn.course.UPDATE`` scope on the refresh token.
        """
        url = (
            f"https://{self.cfg.api_domain}/learn/api/v1/portal/"
            f"{self.cfg.portal}/course/{course_id}/member"
        )
        # Confirmed working shape: JSON body {"userIds":[zuid,...],"role":...}
        # (unlike the invite, which is form-encoded). Success looks like
        # {"STATUS":"OK","members":[{"id":...,"status":"ACTIVE",...}]}.
        ids = [str(u) for u in user_ids]
        payload = json.dumps({"userIds": ids, "role": role}).encode()
        print(f"[zoho] enroll_member POST {url} userIds={ids} role={role}", flush=True)
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Authorization", f"Zoho-oauthtoken {self.access_token()}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            print(f"[zoho] enroll_member HTTPError {e.code}: {detail[:400]}", flush=True)
            raise RuntimeError(f"Zoho API {e.code} adding members: {detail}") from None
        print(f"[zoho] enroll_member -> {body[:400]}", flush=True)
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"raw": body}
        if isinstance(parsed, dict) and (
            str(parsed.get("status", "")).lower() == "failure"
            or str(parsed.get("result", "")).lower() == "failure"
        ):
            raise RuntimeError(f"Zoho add-members failed: {body[:300]}")
        return parsed

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
        # tell us — so hand off to ensure_course_access / the email sign-up link.
        return "invite_needed"

    def _hub_url(self, suffix: str, env_override: str) -> str:
        return os.environ.get(env_override) or (
            f"https://{self.cfg.api_domain}/learn/api/v1/hubs/{self.cfg.portal}/{suffix}"
        )

    def invite_to_hub(self, email: str, name: str | None = None) -> str:
        """Invite a brand-new person to the hub by email (best-effort).

        Unlike :meth:`enroll_member` (which needs an existing Zuid), this
        provisions the user from just an email, so a buyer who has never touched
        Zoho can be onboarded automatically. Zoho emails them an activation link;
        once they accept they become a hub user with a Zuid and can be enrolled
        into the course (see :meth:`ensure_course_access`).

        Endpoint: ``POST /learn/api/v1/hubs/<hub>/invite`` (override with
        ``ZOHO_HUB_INVITE_URL``); requires the ``ZohoLearn.hubMember.CREATE``
        scope. Never raises for the ordinary cases — returns a status string:
        ``"invited"``, ``"already_invited"``, or ``"invite_error: ..."``.
        """
        email = (email or "").strip()
        if not email:
            return "invite_error: no email"
        user: dict[str, str] = {"emailId": email}
        first, _, last = (name or "").strip().partition(" ")
        if first:
            user["fname"] = first
        if last:
            user["lname"] = last
        url = self._hub_url("invite", "ZOHO_HUB_INVITE_URL")
        # Zoho Learn's invite API is form-encoded, with `userlist` holding a JSON
        # array *string* — NOT a JSON body. A JSON body makes Zoho see userlist as
        # empty ("Parameter userlist should not be empty").
        userlist = json.dumps([user])
        data = urllib.parse.urlencode({"userlist": userlist}).encode()
        print(f"[zoho] invite_to_hub POST {url} userlist={userlist}", flush=True)
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Authorization", f"Zoho-oauthtoken {self.access_token()}")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                status = getattr(resp, "status", None) or getattr(resp, "code", "?")
                body = resp.read().decode("utf-8", "replace")
            print(f"[zoho] invite_to_hub -> HTTP {status}: {body[:900]}", flush=True)
            try:
                parsed = json.loads(body)
            except Exception:
                parsed = {}
            # Zoho can return 2xx with {"status":"failure","reason":...}.
            if isinstance(parsed, dict) and str(parsed.get("status", "")).lower() == "failure":
                reason = str(parsed.get("reason") or body[:150])
                if "already" in reason.lower() or "exist" in reason.lower():
                    return "already_invited"
                return f"invite_failed: {reason}"
            return "invited"
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            print(f"[zoho] invite_to_hub HTTPError {e.code}: {detail[:900]}", flush=True)
            low = detail.lower()
            if e.code == 409 or "already" in low or "exist" in low:
                return "already_invited"
            return f"invite_error: {e.code} {detail[:180]}"
        except Exception as e:  # network/DNS/etc — must never block the buyer
            print(f"[zoho] invite_to_hub exception: {e}", flush=True)
            return f"invite_error: {e}"

    def hub_member_zuid(self, email: str) -> str | None:
        """Resolve a hub member's Zuid by email, or None if not a hub user yet.

        ``GET /learn/api/v1/hubs/<hub>/member`` (override with
        ``ZOHO_HUB_MEMBERS_URL``); requires ``ZohoLearn.hubMember.READ``. Parses
        defensively across the possible response shapes and never raises.
        """
        target = (email or "").strip().lower()
        if not target:
            return None
        override = os.environ.get("ZOHO_HUB_MEMBERS_URL")
        base = f"https://{self.cfg.api_domain}/learn/api/v1/hubs/{self.cfg.portal}"
        candidates = (
            [override]
            if override
            else [f"{base}/members", f"{base}/users", f"{base}/user", f"{base}/member"]
        )
        body = None
        for url in candidates:
            req = urllib.request.Request(url, method="GET")
            req.add_header("Authorization", f"Zoho-oauthtoken {self.access_token()}")
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    raw = resp.read().decode() or "{}"
                print(f"[zoho] hub_member_zuid GET {url} -> {raw[:400]}", flush=True)
                body = json.loads(raw)
                break
            except urllib.error.HTTPError as e:
                print(f"[zoho] hub_member_zuid GET {url} -> HTTP {e.code}", flush=True)
            except Exception as e:
                print(f"[zoho] hub_member_zuid GET {url} error: {e}", flush=True)
        if body is None:
            return None
        for member in _iter_member_dicts(body):
            if (member.get("emailId") or member.get("email") or "").strip().lower() == target:
                zuid = self._member_zuid(member)
                print(f"[zoho] hub_member_zuid({target}) -> {zuid}", flush=True)
                return zuid
        print(f"[zoho] hub_member_zuid({target}) -> not found in members list", flush=True)
        return None

    def ensure_course_access(self, course_id: str, email: str, name: str | None = None) -> str:
        """Get a paid buyer into the course, provisioning them if needed.

        Returns a status string (never raises for ordinary cases):
          ``"already_member"`` — already on the course roster,
          ``"enrolled"``       — was a hub user; added to the course now,
          ``"invited"`` / ``"already_invited"`` — brand-new; invited to the hub
                                 (they'll be auto-enrolled on a later poll once
                                 they accept),
          ``"awaiting_signup"`` — self-signup mode: no Zoho invite is sent; the
                                 buyer signs up from our own email and is enrolled
                                 on a later poll once they do,
          ``"enroll_error: ..."`` / ``"invite_error: ..."`` — surfaced, not raised.
        """
        if self.find_member(course_id, email):
            return "already_member"
        zuid = self.hub_member_zuid(email)
        if zuid:
            try:
                self.enroll_member(course_id, [zuid], role="MEMBER")
                return "enrolled"
            except Exception as e:
                return f"enroll_error: {e}"
        # Not a hub user yet. In self-signup mode we deliberately do NOT fire
        # Zoho's invite (its email content isn't editable) — the buyer gets our
        # own branded email inviting them to self-sign-up, and is picked up here
        # on a later poll once they have.
        if self.cfg.self_signup:
            return "awaiting_signup"
        return self.invite_to_hub(email, name)


_SUBJECT_RE = re.compile(r"^\s*(?P<name>.+?)\s+has completed course\s+(?P<course>.+?)\.?\s*$")


def parse_completion_subject(subject: str) -> tuple[str, str] | None:
    """Parse '<Name> has completed course <Course>.' -> (name, course_name)."""
    m = _SUBJECT_RE.match(subject or "")
    if not m:
        return None
    return m.group("name").strip(), m.group("course").strip()
