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


def process_subject(
    subject: str,
    *,
    dry_run: bool = False,
    no_email: bool = False,
    cfg=None,
    client=None,
    supabase=None,
) -> str:
    """Handle one completion-email subject end to end. Returns a status line.

    Reused by the CLI and the mailbox poller. Optional cfg/client/supabase let a
    caller reuse connections across many messages. Raises on hard failures
    (missing config); soft outcomes (unmapped course, unresolved name, already
    issued) are returned as strings.
    """
    from certissuer.zoho import ZohoClient, ZohoConfig, parse_completion_subject

    parsed = parse_completion_subject(subject)
    if not parsed:
        return f"IGNORED (unrecognized subject): {subject!r}"
    name, course_name = parsed

    cfg = cfg or ZohoConfig.from_env()
    target = cfg.target_for_course_name(course_name)
    if not target:
        # Surface this — a silent "IGNORED" on a green run is how completions get
        # missed. A GitHub Actions ::warning:: shows it on the run summary.
        known = ", ".join(sorted(cfg.course_map.keys())) or "(none configured)"
        print(
            f"::warning::Zoho completion course not mapped: {course_name!r}. "
            f"Add it to ZOHO_COURSE_MAP so this learner gets a certificate. "
            f"Currently mapped: {known}.",
            flush=True,
        )
        return f"IGNORED (course not mapped): {course_name!r}"

    client = client or ZohoClient(cfg)
    email = client.resolve_email(target.zoho_course_id, name)
    if not email:
        return f"SKIPPED (couldn't uniquely resolve email for {name!r})"

    if supabase is None:
        from certissuer.client import get_service_client

        supabase = get_service_client()

    if _already_issued(supabase, email, target.course):
        return f"SKIPPED (already issued): {name} <{email}> / {target.course}"

    if dry_run:
        return f"WOULD issue+email {target.course} to {name} <{email}>"

    from certissuer.issuer import IssuanceInput, issue_certificate

    result = issue_certificate(
        IssuanceInput(candidate_name=name, candidate_email=email, course=target.course)
    )
    line = f"ISSUED {result.certificate_id} for {name} <{email}>"
    if not no_email:
        from certissuer.emailer import send_certificate_email

        er = send_certificate_email(result.certificate_id, to=email)
        line += f"; emailed to {er.to}"
    return line


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

    # Build a subject if given name+course instead.
    subject = args.subject
    if not subject:
        if args.name and args.course_name:
            subject = f"{args.name.strip()} has completed course {args.course_name.strip()}."
        else:
            print("Provide --subject, or both --name and --course-name.", file=sys.stderr)
            return 2

    line = process_subject(subject, dry_run=args.dry_run, no_email=args.no_email)
    print(line)
    return 1 if line.startswith("SKIPPED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
