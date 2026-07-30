#!/usr/bin/env python3
"""AA Impact Inc. — certificate issuance CLI (upstream).

Input participant details on the command line; this mints a unique certificate
ID, generates the certificate PDF, uploads it to Supabase Storage, and writes
the system-of-record row that the public verifier reads.

Examples
--------
Issue a real certificate (requires SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY):

    python issue_certificate.py \
        --name "Priya Sharma" \
        --email "priya.sharma@example.com" \
        --company "Example Manufacturing Pvt Ltd" \
        --course GHG \
        --completed-at 2026-07-15

Preview everything (ID, hash, PDF) without touching the database:

    python issue_certificate.py --name "Test User" --email t@example.com \
        --course GHG --dry-run --pdf-out ./preview.pdf
"""

from __future__ import annotations

import argparse
import json
import sys

from certissuer import config
from certissuer.issuer import IssuanceInput, build_record, issue_certificate


def _load_dotenv() -> None:
    """Load a local .env if python-dotenv is installed; ignore otherwise."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="issue_certificate.py",
        description="Issue an AA Impact training certificate.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--name", required=True, help="Participant full name.")
    p.add_argument("--email", required=True, help="Participant email address.")
    p.add_argument("--company", default=None, help="Participant company (optional).")
    p.add_argument(
        "--course",
        required=True,
        choices=config.VALID_COURSES,
        help="Course completed.",
    )
    p.add_argument(
        "--completed-at",
        default=None,
        help="Completion date (YYYY-MM-DD) or ISO datetime. Defaults to now.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute ID/hash and render the PDF without writing to Supabase.",
    )
    p.add_argument(
        "--pdf-out",
        default=None,
        help="On --dry-run, also write the rendered PDF to this local path.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Print the resulting record as JSON.",
    )
    return p


def _warn_if_unconfirmed(course: str) -> None:
    meta = config.course_meta(course)
    if not meta.confirmed:
        print(
            f"WARNING: course_code {meta.course_code!r} for course {course!r} "
            "is a placeholder and has not been confirmed against the registry. "
            "Confirm it before issuing production certificates.",
            file=sys.stderr,
        )


def _print_result(record: dict, as_json: bool, header: str) -> None:
    if as_json:
        printable = {k: v for k, v in record.items() if not k.startswith("_")}
        print(json.dumps(printable, indent=2))
        return
    print(header)
    print(f"  Certificate ID : {record['certificate_id']}")
    print(f"  Name           : {record['candidate_name']}")
    print(f"  Email          : {record['candidate_email']}")
    if record.get("company"):
        print(f"  Company        : {record['company']}")
    print(f"  Course         : {record['course']} ({record['course_code']})")
    print(f"  Completed at   : {record['completed_at']}")
    print(f"  Integrity hash : {record['cert_hash']}")
    print(f"  PDF path       : {record['pdf_storage_path']}")
    print(f"  Status         : {record['status']}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _warn_if_unconfirmed(args.course)

    data = IssuanceInput(
        candidate_name=args.name,
        candidate_email=args.email,
        course=args.course,
        company=args.company,
        completed_at=args.completed_at,
    )

    if args.dry_run:
        record = build_record(data)
        if args.pdf_out:
            from certissuer.pdf import render_certificate_pdf

            pdf_bytes = render_certificate_pdf(
                candidate_name=record["candidate_name"],
                course_title=record["_course_title"],
                course=record["course"],
                completed_at=record["_completed_dt"],
                certificate_id=record["certificate_id"],
                company=record.get("company"),
            )
            with open(args.pdf_out, "wb") as fh:
                fh.write(pdf_bytes)
            print(f"Wrote preview PDF to {args.pdf_out}", file=sys.stderr)
        _print_result(record, args.json, "DRY RUN — nothing was written to Supabase:")
        return 0

    _load_dotenv()
    result = issue_certificate(data)
    _print_result(vars(result), args.json, "Certificate issued:")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
