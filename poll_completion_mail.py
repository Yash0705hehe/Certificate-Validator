#!/usr/bin/env python3
"""Poll the certificate@ mailbox (via Microsoft Graph) for Zoho completion
emails and issue + email certificates for them.

Run on a schedule (GitHub Actions). Reads recent messages from the Zoho sender
whose subject says "<Learner> has completed course <Course>.", then hands each
subject to the same issuance path used elsewhere. Idempotent — already-issued
learners are skipped — so overlapping polling windows never duplicate.

Usage:
  python poll_completion_mail.py                 # real run
  python poll_completion_mail.py --dry-run       # resolve + report only
  python poll_completion_mail.py --lookback 6    # look back N hours (default 3)
"""

from __future__ import annotations

import argparse
import sys

# The Zoho Learn notification sender and the subject marker to match.
ZOHO_SENDER = "noreply@mail.zoholearn.in"
SUBJECT_MARKER = "has completed course"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Poll mailbox for Zoho completion emails.")
    p.add_argument("--dry-run", action="store_true", help="Resolve + report; no writes/emails.")
    p.add_argument("--no-email", action="store_true", help="Issue but do not email.")
    p.add_argument(
        "--lookback",
        type=int,
        default=3,
        help="How many hours of recent mail to scan (default 3; overlap is safe).",
    )
    p.add_argument(
        "--sender", default=ZOHO_SENDER, help="Sender address to match (override if needed)."
    )
    args = p.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    from certissuer.msgraph import MSGraphClient, MSGraphConfig
    from issue_from_completion import process_subject

    client = MSGraphClient(MSGraphConfig.from_env())
    subjects = client.completion_subjects(args.sender, SUBJECT_MARKER, args.lookback)
    print(f"Found {len(subjects)} completion email(s) in the last {args.lookback}h.")

    # Reuse Zoho + Supabase connections across all subjects.
    cfg = zoho = supabase = None
    if subjects and not args.dry_run:
        from certissuer.client import get_service_client
        from certissuer.zoho import ZohoClient, ZohoConfig

        cfg = ZohoConfig.from_env()
        zoho = ZohoClient(cfg)
        supabase = get_service_client()

    failures = 0
    for subject in subjects:
        try:
            line = process_subject(
                subject,
                dry_run=args.dry_run,
                no_email=args.no_email,
                cfg=cfg,
                client=zoho,
                supabase=supabase,
            )
            print(f"  {line}")
        except Exception as e:  # keep processing the rest
            failures += 1
            print(f"  ERROR for {subject!r}: {e}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
