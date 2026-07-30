#!/usr/bin/env python3
"""Email an already-issued certificate to a recipient.

Downloads the certificate PDF from Supabase Storage and emails it via Resend.

    python send_certificate_email.py --certificate-id AAI-GHG-CA-1ef1a25344d59f69
    python send_certificate_email.py --certificate-id AAI-... --to someone@example.com

Requires SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY and RESEND_API_KEY in the
environment (see .env.example).
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="send_certificate_email.py",
        description="Email an issued AA Impact certificate.",
    )
    p.add_argument("--certificate-id", required=True, help="Certificate ID to send.")
    p.add_argument(
        "--to",
        default=None,
        help="Recipient email (defaults to the certificate's candidate email).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be sent without contacting Supabase/Resend.",
    )
    args = p.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    from certissuer.emailer import send_certificate_email

    result = send_certificate_email(
        args.certificate_id, to=args.to, dry_run=args.dry_run
    )
    if result.sent:
        print(f"Emailed {result.certificate_id} to {result.to} (id: {result.provider_id})")
    else:
        print(
            f"DRY RUN — would email {result.certificate_id} to {result.to}; "
            "nothing was sent."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
