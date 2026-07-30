#!/usr/bin/env python3
"""Daily sync: issue + email certificates for Zoho Learn course completions.

For each configured Zoho course, fetch its report, find learners marked
completed, and for anyone who does not already hold an active certificate for
that course, issue one and email it. Idempotent: the certificates table is the
source of truth, so re-runs never double-issue or double-email.

Usage:
  python sync_zoho.py                 # real run (issues + emails)
  python sync_zoho.py --dry-run       # list who WOULD be issued; no writes
  python sync_zoho.py --dump          # print raw Zoho reports and exit
  python sync_zoho.py --no-email      # issue but don't email

Env: the Supabase, Resend and Zoho variables (see .env.example / ZOHO_SETUP.md).
"""

from __future__ import annotations

import argparse
import json
import sys

from certissuer import config
from certissuer.zoho import ZohoClient, ZohoConfig, iter_completed_learners


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
    p = argparse.ArgumentParser(description="Sync Zoho Learn completions to certificates.")
    p.add_argument("--dry-run", action="store_true", help="List actions without writing.")
    p.add_argument("--dump", action="store_true", help="Print raw Zoho reports and exit.")
    p.add_argument("--no-email", action="store_true", help="Issue but do not email.")
    args = p.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    cfg = ZohoConfig.from_env()
    client = ZohoClient(cfg)

    if args.dump:
        for zoho_course_id in cfg.course_map:
            print(f"===== raw report: course {zoho_course_id} =====")
            print(json.dumps(client.fetch_course_report(zoho_course_id), indent=2)[:8000])
        return 0

    # Validate configured course keys against our known courses up front.
    for our_course in cfg.course_map.values():
        if our_course not in config.VALID_COURSES:
            print(
                f"ERROR: ZOHO_COURSE_MAP maps to unknown course {our_course!r}. "
                f"Valid: {', '.join(config.VALID_COURSES)}",
                file=sys.stderr,
            )
            return 2

    supabase = None
    if not args.dry_run:
        from certissuer.client import get_service_client

        supabase = get_service_client()
    else:
        # dry-run still needs to read the table to show accurate skip decisions
        try:
            from certissuer.client import get_service_client

            supabase = get_service_client()
        except Exception:
            print("(dry-run: no Supabase creds; duplicate detection disabled)")

    issued = emailed = skipped = failed = 0

    for zoho_course_id, our_course in cfg.course_map.items():
        report = client.fetch_course_report(zoho_course_id)
        completions = iter_completed_learners(report)
        print(f"Course {our_course} (Zoho {zoho_course_id}): {len(completions)} completed learner(s).")

        for c in completions:
            if supabase is not None and _already_issued(supabase, c.email, our_course):
                skipped += 1
                continue

            if args.dry_run:
                print(f"  WOULD issue+email: {c.name} <{c.email}> ({our_course})")
                issued += 1
                continue

            try:
                from certissuer.issuer import IssuanceInput, issue_certificate

                result = issue_certificate(
                    IssuanceInput(
                        candidate_name=c.name,
                        candidate_email=c.email,
                        course=our_course,
                        completed_at=c.completed_at,  # None -> issuance uses now
                    )
                )
                issued += 1
                print(f"  issued {result.certificate_id} for {c.name} <{c.email}>")

                if not args.no_email:
                    from certissuer.emailer import send_certificate_email

                    send_certificate_email(result.certificate_id, to=c.email)
                    emailed += 1
                    print(f"    emailed to {c.email}")
            except Exception as e:  # keep going; report at the end
                failed += 1
                print(f"  FAILED for {c.name} <{c.email}>: {e}", file=sys.stderr)

    verb = "would issue" if args.dry_run else "issued"
    print(f"\nSummary: {verb} {issued}, emailed {emailed}, skipped (already issued) {skipped}, failed {failed}.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
