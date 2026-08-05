"""Email a participant their certificate PDF via Brevo.

Brevo is used (instead of a domain-DNS sender) because the AA Impact domain's
DNS is on Wix, which can't add the subdomain MX records other providers need.
Brevo works with a single verified sender address (verified by clicking a link
sent to that inbox), so no DNS records are required to start. Adding Brevo's
DKIM TXT records in Wix later improves inbox placement, but isn't required.

Runs inside GitHub Actions (which has the service-role key and network). It
downloads the certificate PDF from the private storage bucket and sends it as
an attachment through the Brevo transactional-email API.

Configuration (environment):
  BREVO_API_KEY   required — your Brevo API key.
  BREVO_FROM      sender, "Name <email>" form, e.g.
                  "AA Impact Academy <certificate@aaimpactinc.com>". The email
                  must be a verified sender (or on a verified domain) in Brevo.

Only the standard library is used for the HTTP call.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import config
from .client import get_service_client
from .timeutil import display_date

BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"
DEFAULT_FROM = "AA Impact Academy <certificate@aaimpactinc.com>"


@dataclass
class EmailResult:
    to: str
    certificate_id: str
    provider_id: str | None  # Brevo messageId when sent
    sent: bool


def _parse_sender(value: str) -> tuple[str, str]:
    """Parse "Name <email>" (or a bare email) into (name, email)."""
    m = re.match(r"^\s*(.*?)\s*<\s*([^>]+?)\s*>\s*$", value)
    if m:
        return (m.group(1) or "AA Impact Academy"), m.group(2)
    return "AA Impact Academy", value.strip()


def _completed_display(completed_at_iso: str) -> str:
    from datetime import datetime

    try:
        return display_date(datetime.fromisoformat(completed_at_iso))
    except Exception:
        return completed_at_iso[:10]


def compose(name: str, certificate_id: str, course: str, completed_display: str):
    """Return (subject, html) for the certificate email."""
    subject = f"Your AA Impact {course} certificate"
    html = f"""\
<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;color:#17242e;line-height:1.6">
  <p>Dear {name},</p>
  <p>Congratulations on completing your AA Impact training. Your certificate is
  attached to this email as a PDF.</p>
  <table style="border-collapse:collapse;margin:16px 0">
    <tr><td style="padding:4px 12px 4px 0;color:#6b7280">Certificate ID</td>
        <td style="padding:4px 0;font-family:monospace;font-weight:bold">{certificate_id}</td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#6b7280">Completion date</td>
        <td style="padding:4px 0">{completed_display}</td></tr>
  </table>
  <p>You can verify this certificate at any time using the Certificate ID above
  together with your name or completion date on the AA Impact website.</p>
  <p style="color:#6b7280;font-size:13px">AA Impact Inc. &middot; www.aaimpactinc.com</p>
</div>"""
    return subject, html


def compose_enrolment(name: str, course: str, course_url: str):
    """Return (subject, html) for the post-payment welcome / course-access email.

    This is the branded email that *replaces* Zoho's own hub-invite email in
    self-signup mode (see certissuer.zoho — ZOHO_SELF_SIGNUP): the button links
    to the hub sign-up page, and once the buyer creates their account the
    reconcile job adds them to the course automatically.
    """
    course_label = {
        "GHG": "GHG Accounting Course",
        "Nature": "Nature Course",
        "GHG_Nature_Bundle": "GHG + Nature Bundle",
    }.get(course, course)
    subject = f"Start your {course_label} — AA Impact"
    button = (
        f'<a href="{course_url}" style="display:inline-block;background:#17242e;'
        'color:#ffffff;text-decoration:none;padding:12px 22px;border-radius:6px;'
        f'font-weight:bold">Set up my course access</a>'
        if course_url
        else ""
    )
    html = f"""\
<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;color:#17242e;line-height:1.6">
  <p>Dear {name},</p>
  <p>Thank you for purchasing the <strong>{course_label}</strong> with AA Impact —
  your payment is confirmed.</p>
  <p>To get started, set up your learning account using <strong>this same email
  address</strong> (the one you paid with), so your progress and certificate are
  recorded against you:</p>
  <p style="margin:22px 0">{button}</p>
  <p>Once you've created your account, we'll add you to the course automatically —
  usually <strong>within 15 minutes</strong>. You'll find it under
  <strong>My Courses</strong> when you log in.</p>
  <p>When you finish, your official AA Impact certificate is issued and emailed to
  you automatically — nothing else to do.</p>
  <p>Questions? Just reply to this email.</p>
  <p style="color:#6b7280;font-size:13px">AA Impact Inc. &middot; www.aaimpactinc.com</p>
</div>"""
    return subject, html


def send_enrolment_email(
    to: str,
    name: str,
    course: str,
    course_url: str,
    dry_run: bool = False,
) -> EmailResult:
    """Email a buyer their course-access link after a successful payment."""
    if dry_run:
        return EmailResult(to=to, certificate_id="", provider_id=None, sent=False)

    api_key = os.environ.get("BREVO_API_KEY")
    if not api_key:
        raise RuntimeError(
            "BREVO_API_KEY is not set. Add it as a repository secret (see README)."
        )
    sender_name, sender_email = _parse_sender(os.environ.get("BREVO_FROM", DEFAULT_FROM))
    subject, html = compose_enrolment(name, course, course_url)
    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": to.strip()}],
        "subject": subject,
        "htmlContent": html,
    }
    provider_id = _send_via_brevo(payload, api_key)
    return EmailResult(to=to.strip(), certificate_id="", provider_id=provider_id, sent=True)


def _send_via_brevo(payload: dict, api_key: str) -> str:
    req = urllib.request.Request(
        BREVO_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "api-key": api_key,
            "content-type": "application/json",
            "accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8") or "{}")
            return body.get("messageId", "")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"Brevo API error {e.code}: {detail}") from None


def send_certificate_email(
    certificate_id: str,
    to: str | None = None,
    dry_run: bool = False,
) -> EmailResult:
    """Email the certificate PDF for ``certificate_id`` to ``to`` (or the
    candidate's own email). Set ``dry_run`` to skip Supabase/Brevo and just
    report what would happen."""
    if dry_run:
        return EmailResult(
            to=to or "<candidate email>",
            certificate_id=certificate_id,
            provider_id=None,
            sent=False,
        )

    supabase = get_service_client()
    row = (
        supabase.table("certificates")
        .select(
            "certificate_id, candidate_name, candidate_email, course, "
            "completed_at, pdf_storage_path, status"
        )
        .ilike("certificate_id", certificate_id.strip())
        .single()
        .execute()
    ).data
    if not row:
        raise RuntimeError(f"No certificate found for id {certificate_id!r}.")

    recipient = (to or row["candidate_email"]).strip()
    if not row.get("pdf_storage_path"):
        raise RuntimeError(
            f"Certificate {row['certificate_id']} has no PDF on file; cannot email it."
        )

    pdf_bytes = supabase.storage.from_(config.STORAGE_BUCKET).download(
        row["pdf_storage_path"]
    )

    subject, html = compose(
        row["candidate_name"],
        row["certificate_id"],
        row["course"],
        _completed_display(row["completed_at"]),
    )

    api_key = os.environ.get("BREVO_API_KEY")
    if not api_key:
        raise RuntimeError(
            "BREVO_API_KEY is not set. Add it as a repository secret (see README)."
        )
    sender_name, sender_email = _parse_sender(os.environ.get("BREVO_FROM", DEFAULT_FROM))

    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": recipient}],
        "subject": subject,
        "htmlContent": html,
        "attachment": [
            {
                "name": row["pdf_storage_path"],
                "content": base64.b64encode(pdf_bytes).decode("ascii"),
            }
        ],
    }
    provider_id = _send_via_brevo(payload, api_key)
    return EmailResult(
        to=recipient,
        certificate_id=row["certificate_id"],
        provider_id=provider_id,
        sent=True,
    )
