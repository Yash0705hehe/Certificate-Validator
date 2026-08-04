#!/usr/bin/env python3
"""Poll Wix Forms for paid course buyers and enrol them — the email-capture hook.

The AA Impact site charges through a Wix **Forms & Payments** form, so a buyer's
name + email land in the form submission (Wix never pushes them to us, and the
site has no Pricing Plans/Stores event to hook). This poller — run on a schedule
by GitHub Actions — lists CONFIRMED (paid) submissions via the Wix Forms API and
runs each one through the existing purchase pipeline:

  Wix "Payment" form submission (CONFIRMED)
     → this poller reads name + email + course
        → process_purchase(): records the buyer in Supabase (idempotent),
          best-effort auto-enrols / invites them into the Zoho Learn course,
          and emails their course-access link.

Idempotency is inherited from ``enroll_from_purchase.process_purchase`` (unique
on ``(lower(email), course)``), so re-polling the same submission is a no-op —
no "last seen" cursor to maintain.

Usage:
  python poll_wix_submissions.py            # process new paid buyers
  python poll_wix_submissions.py --dry-run  # list who WOULD be enrolled; no writes
  python poll_wix_submissions.py --no-enroll --no-email   # record only

Config comes from the WIX_* environment (see certissuer/wix.py and
docs/WIX_ENROLMENT_SETUP.md). The same Supabase / Brevo / Zoho env the other
workflows use must also be present for the non-dry-run path.
"""

from __future__ import annotations

import argparse
import sys


def poll(*, dry_run: bool = False, no_email: bool = False, no_enroll: bool = False) -> int:
    from certissuer.wix import WixClient, WixConfig

    cfg = WixConfig.from_env()
    client = WixClient(cfg)
    buyers = client.buyers()

    if not buyers:
        print("No CONFIRMED Wix submissions to process.")
        return 0

    print(f"Found {len(buyers)} confirmed submission(s) across forms {list(cfg.form_course_map)}.")

    # Reuse the exact purchase pipeline the manual/dispatch path already uses.
    from enroll_from_purchase import process_purchase

    supabase = None
    if not dry_run:
        from certissuer.client import get_service_client

        supabase = get_service_client()

    processed = skipped = errors = 0
    for b in buyers:
        try:
            line = process_purchase(
                b.name,
                b.email,
                b.course,
                order_id=b.submission_id or None,
                dry_run=dry_run,
                no_email=no_email,
                no_enroll=no_enroll,
                supabase=supabase,
            )
            print(f"  {line}")
            if line.startswith("SKIPPED") or line.startswith("WOULD"):
                skipped += 1
            else:
                processed += 1
        except Exception as exc:  # one bad row must not stop the batch
            errors += 1
            print(f"  ERROR {b.name} <{b.email}> / {b.course}: {exc}", file=sys.stderr)

    print(
        f"Done. processed={processed} skipped/would={skipped} errors={errors} "
        f"(dry_run={dry_run})."
    )
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Poll Wix Forms for paid buyers and enrol them (idempotent)."
    )
    p.add_argument("--dry-run", action="store_true", help="List who would be enrolled; no writes.")
    p.add_argument("--no-email", action="store_true", help="Record/enrol but do not email.")
    p.add_argument("--no-enroll", action="store_true", help="Skip the Zoho enrol/invite attempt.")
    args = p.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    return poll(dry_run=args.dry_run, no_email=args.no_email, no_enroll=args.no_enroll)


if __name__ == "__main__":
    raise SystemExit(main())
