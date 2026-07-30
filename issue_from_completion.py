#!/usr/bin/env python3
"""Issue + email a certificate from a Zoho Learn completion notification.

Triggered (via GitHub repository_dispatch from a Power Automate flow) whenever
Zoho emails the admin "<Learner> has completed course <Course>." It:
  1. parses the learner name + course name from the email subject,
  2. maps the course to our course + its Zoho course id (ZOHO_COURSE_MAP),
  3. resolves the learner's email from the Zoho course roster,
  4. issues the certificate and emails it — unless one already exists (idempotent).

Usage:
  python issue_from_completion.py --subject "Ananya Mehra has completed course GHG Accounting Course."
  python issue_from_completion.py --name "Ananya Mehra" --course-name "GHG Accounting Course"
  add --dry-run to resolve + report without writing/emailing.
"""

from __future__ import annotations

import argparse
import sys

from certissuer.zoho import ZohoClient, ZohoConfig, parse_completion_subject


def _already_issued(supabase, email: str, course: str) -> bool:
    res = (
        supabase.table("certificates")
        .select("certificate_id")
        .ilike("candidate_email", email)
        .eq("course", course)
        .eq("status", "active")
        .limit(1)
        .execute()
    )
    return bool(res.data)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Issue a certificate from a Zoho completion email.")
    p.add_argument("--subject", help='Email subject: "<Name> has completed course <Course>."')
    p.add_argument("--name", help="Learner name (if not passing --subject).")
    p.add_argument("--course-name", help="Zoho course name (if not passing --subject).")
    p.add_argument("--dry-run", action="store_true", help="Resolve + report; no writes/emails.")
    p.add_argument("--no-email", action="store_true", help="Issue but do not email.")
    args = p.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    # Determine learner name + course name.
    if args.subject:
        parsed = parse_completion_subject(args.subject)
        if not parsed:
            print(f"Subject not recognized: {args.subject!r}", file=sys.stderr)
            return 2
        name, course_name = parsed
    elif args.name and args.course_name:
        name, course_name = args.name.strip(), args.course_name.strip()
    else:
        print("Provide --subject, or both --name and --course-name.", file=sys.stderr)
        return 2

    cfg = ZohoConfig.from_env()
    target = cfg.target_for_course_name(course_name)
    if not target:
        print(
            f"Course {course_name!r} is not in ZOHO_COURSE_MAP — ignoring "
            "(only mapped courses are auto-issued).",
            file=sys.stderr,
        )
        return 0  # not an error: we simply don't handle this course

    client = ZohoClient(cfg)
    email = client.resolve_email(target.zoho_course_id, name)
    if not email:
        print(
            f"Could not uniquely resolve an email for learner {name!r} in the "
            f"course roster — skipping. Check the name matches Zoho exactly.",
            file=sys.stderr,
        )
        return 1

    print(f"Resolved: {name} <{email}> → course {target.course}")

    # Dedup + issue.
    from certissuer.client import get_service_client

    supabase = get_service_client()
    if _already_issued(supabase, email, target.course):
        print(f"Already issued for {email} / {target.course} — nothing to do.")
        return 0

    if args.dry_run:
        print(f"DRY RUN — would issue + email {target.course} certificate to {email}.")
        return 0

    from certissuer.issuer import IssuanceInput, issue_certificate

    result = issue_certificate(
        IssuanceInput(candidate_name=name, candidate_email=email, course=target.course)
    )
    print(f"Issued {result.certificate_id} for {name} <{email}>")

    if not args.no_email:
        from certissuer.emailer import send_certificate_email

        er = send_certificate_email(result.certificate_id, to=email)
        print(f"Emailed to {er.to} (provider id: {er.provider_id})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
