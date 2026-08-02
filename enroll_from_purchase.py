#!/usr/bin/env python3
"""Record a paid-course buyer and give them access — the Wix checkout hook.

Triggered (via GitHub repository_dispatch from a Velo backend event on the paid
aaimpactinc.com site) whenever someone completes a course purchase. It:
  1. records the buyer (name + email + order) in the Supabase ``enrolments``
     table — idempotent on (email, course), so a retried webhook is a no-op,
  2. best-effort auto-enrols them into the Zoho Learn course if they're already
     a portal user (Zoho's add-member API needs an existing Zoho id),
  3. emails them their Zoho course-access link so a brand-new buyer can sign up
     and start immediately.

Course completion → certificate is handled by the existing pipeline
(issue_from_completion.py), so nothing else is needed here.

Usage:
  python enroll_from_purchase.py --name "Ravi Kumar" --email ravi@example.com --course GHG
  add --dry-run to resolve + report without writing/enrolling/emailing.

Course-access links come from the COURSE_ACCESS_URLS env var, a JSON map of our
course key to the Zoho Learn course URL, e.g.
  COURSE_ACCESS_URLS={"GHG": "https://learn.zoho.in/portal/aa-impact/course/58084000000002174"}
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from certissuer import config


def _course_access_url(course: str) -> str:
    raw = os.environ.get("COURSE_ACCESS_URLS", "").strip()
    if not raw:
        return ""
    try:
        return str(json.loads(raw).get(course, "")).strip()
    except Exception:
        return ""


def _existing_enrolment(supabase, email: str, course: str):
    res = (
        supabase.table("enrolments")
        .select("id, buyer_email, course, zoho_enrolled, enrol_email_sent")
        .ilike("buyer_email", email)
        .eq("course", course)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def process_purchase(
    name: str,
    email: str,
    course: str,
    *,
    order_id: str | None = None,
    amount: float | None = None,
    currency: str | None = None,
    dry_run: bool = False,
    no_email: bool = False,
    no_enroll: bool = False,
    supabase=None,
) -> str:
    """Handle one paid purchase end to end. Returns a status line.

    Raises on hard failures (bad course, missing config); soft outcomes
    (already enrolled) are returned as strings.
    """
    name = (name or "").strip()
    email = (email or "").strip()
    if not name or not email:
        raise ValueError("Both --name and --email are required.")
    if course not in config.VALID_COURSES:
        raise ValueError(
            f"Unknown course {course!r}; expected one of {', '.join(config.VALID_COURSES)}."
        )

    if supabase is None:
        from certissuer.client import get_service_client

        supabase = get_service_client()

    existing = _existing_enrolment(supabase, email, course)
    if existing and existing.get("enrol_email_sent"):
        return f"SKIPPED (already enrolled): {name} <{email}> / {course}"

    course_url = _course_access_url(course)

    if dry_run:
        return (
            f"WOULD enrol {name} <{email}> in {course} "
            f"(access link: {course_url or 'MISSING — set COURSE_ACCESS_URLS'})"
        )

    # 1) Record the buyer. The pre-check above makes this idempotent for the
    #    common case; the unique index on (lower(email), course) is the backstop
    #    against a genuinely concurrent double-fire.
    if existing:
        saved = existing
    else:
        row = {
            "buyer_name": name,
            "buyer_email": email,
            "course": course,
            "source": "wix",
            "wix_order_id": order_id,
            "amount": amount,
            "currency": currency,
        }
        row = {k: v for k, v in row.items() if v is not None}
        ins = supabase.table("enrolments").insert(row).execute()
        saved = ins.data[0] if ins.data else _existing_enrolment(supabase, email, course)
    if not saved:
        raise RuntimeError(f"Failed to record enrolment for {email} / {course}.")

    notes: list[str] = []

    # 2) Best-effort Zoho auto-enrol (only works for existing portal users).
    zoho_status = "skipped"
    if not no_enroll:
        try:
            from certissuer.zoho import ZohoClient, ZohoConfig

            cfg = ZohoConfig.from_env()
            zoho_course_id = cfg.zoho_course_id_for_key(course)
            if zoho_course_id:
                zoho_status = ZohoClient(cfg).try_enroll_by_email(zoho_course_id, email)
            else:
                zoho_status = "no_course_id"
        except Exception as exc:  # never block the buyer's access on a Zoho hiccup
            zoho_status = f"error: {exc}"
    notes.append(f"zoho={zoho_status}")

    # 3) Email the course-access link (so new buyers can sign up + start).
    email_sent = False
    if not no_email and course_url:
        from certissuer.emailer import send_enrolment_email

        er = send_enrolment_email(email, name, course, course_url)
        email_sent = er.sent
        notes.append(f"emailed={er.to}")
    elif not course_url:
        notes.append("email=skipped(no COURSE_ACCESS_URLS)")

    from datetime import datetime, timezone

    supabase.table("enrolments").update(
        {
            "zoho_enrolled": zoho_status in ("enrolled", "already_member"),
            "enrol_email_sent": email_sent,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", saved["id"]).execute()

    return f"ENROLLED {name} <{email}> / {course} ({'; '.join(notes)})"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Record a paid buyer, auto-enrol, and email their course link."
    )
    p.add_argument("--name", required=True, help="Buyer full name.")
    p.add_argument("--email", required=True, help="Buyer email address.")
    p.add_argument(
        "--course",
        required=True,
        choices=config.VALID_COURSES,
        help="Course purchased.",
    )
    p.add_argument("--order-id", default=None, help="Wix order id (optional).")
    p.add_argument("--amount", type=float, default=None, help="Amount paid (optional).")
    p.add_argument("--currency", default=None, help="Currency code (optional).")
    p.add_argument("--dry-run", action="store_true", help="Resolve + report; no writes.")
    p.add_argument("--no-email", action="store_true", help="Record/enrol but do not email.")
    p.add_argument("--no-enroll", action="store_true", help="Skip the Zoho enrol attempt.")
    args = p.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    line = process_purchase(
        args.name,
        args.email,
        args.course,
        order_id=args.order_id,
        amount=args.amount,
        currency=args.currency,
        dry_run=args.dry_run,
        no_email=args.no_email,
        no_enroll=args.no_enroll,
    )
    print(line)
    return 1 if line.startswith("SKIPPED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
