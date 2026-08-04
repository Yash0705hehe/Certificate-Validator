#!/usr/bin/env python3
"""Enrol paid buyers into their Zoho course once they've accepted the hub invite.

At purchase time a buyer is *invited* to the hub (Velo → wix_enrolment), but with
the course set to "Added Learners Only" they must then be **added** to the course
— which can only happen after they accept (become a hub user with a resolvable
Zuid). The purchase hook can't do that yet, so this scheduled job reconciles:
for every recorded buyer not yet enrolled in Zoho, it re-runs
``ensure_course_access``, which adds them the moment their acceptance makes a
Zuid resolvable. Uses Supabase + Zoho only — not the blocked Wix submissions API.

Usage:
  python reconcile_enrolments.py            # enrol any now-accepted buyers
  python reconcile_enrolments.py --dry-run  # report only, no writes/enrolments
"""

from __future__ import annotations

import argparse


def reconcile(dry_run: bool = False) -> int:
    from certissuer.zoho import ZohoClient, ZohoConfig

    cfg = ZohoConfig.from_env()
    if not cfg.auto_enroll:
        print("ZOHO_AUTO_ENROLL is off — nothing to reconcile.")
        return 0

    from certissuer.client import get_service_client

    supabase = get_service_client()
    client = ZohoClient(cfg)

    rows = (
        supabase.table("enrolments")
        .select("id, buyer_name, buyer_email, course, zoho_enrolled")
        .eq("zoho_enrolled", False)
        .execute()
    ).data or []
    print(f"{len(rows)} buyer(s) awaiting course enrolment.")

    enrolled = pending = errors = 0
    for row in rows:
        email = (row.get("buyer_email") or "").strip()
        course = row.get("course")
        course_id = cfg.zoho_course_id_for_key(course) if course else None
        if not email or not course_id:
            continue
        try:
            status = client.ensure_course_access(course_id, email, row.get("buyer_name"))
        except Exception as exc:  # never let one row halt the batch
            status = f"error: {exc}"
        print(f"  {email} / {course} -> {status}")

        if status in ("enrolled", "already_member"):
            enrolled += 1
            if not dry_run:
                from datetime import datetime, timezone

                supabase.table("enrolments").update(
                    {
                        "zoho_enrolled": True,
                        "processed_at": datetime.now(timezone.utc).isoformat(),
                    }
                ).eq("id", row["id"]).execute()
        elif status.startswith("error") or "_error" in status:
            errors += 1
        else:
            pending += 1  # invited but not yet accepted — try again next run

    print(
        f"Done. enrolled={enrolled} still_pending={pending} errors={errors} "
        f"(dry_run={dry_run})"
    )
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Enrol accepted buyers into their Zoho course (idempotent)."
    )
    p.add_argument("--dry-run", action="store_true", help="Report only; no writes/enrolments.")
    args = p.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    return reconcile(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
