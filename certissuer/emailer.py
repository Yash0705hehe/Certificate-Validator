"""Email a participant their certificate PDF via Resend.

Runs inside the GitHub Actions workflow (which has the Supabase service-role key
and outbound network). It downloads the certificate PDF from the private storage
bucket and sends it as an attachment through the Resend HTTP API.

Configuration (environment):
  RESEND_API_KEY   required — your Resend API key.
  RESEND_FROM      sender, e.g. "AA Impact Academy <certificates@aaimpactinc.com>".
                   Must be an address on a domain you've verified in Resend.
                   Defaults to that address; override if your verified sender
                   differs.

Only the standard library is used for the HTTP call, so there is no extra
dependency to install.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import config
from .client import get_service_client
from .timeutil import display_date

RESEND_ENDPOINT = "https://api.resend.com/emails"
DEFAULT_FROM = "AA Impact Academy <certificates@aaimpactinc.com>"


@dataclass
class EmailResult:
    to: str
    certificate_id: str
    provider_id: str | None  # Resend message id when sent
    sent: bool


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


def _send_via_resend(payload: dict, api_key: str) -> str:
    req = urllib.request.Request(
        RESEND_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("id", "")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"Resend API error {e.code}: {detail}") from None


def send_certificate_email(
    certificate_id: str,
    to: str | None = None,
    dry_run: bool = False,
) -> EmailResult:
    """Email the certificate PDF for ``certificate_id`` to ``to`` (or the
    candidate's own email). Set ``dry_run`` to skip Supabase/Resend and just
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

    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError(
            "RESEND_API_KEY is not set. Add it as a repository secret (see README)."
        )

    payload = {
        "from": os.environ.get("RESEND_FROM", DEFAULT_FROM),
        "to": [recipient],
        "subject": subject,
        "html": html,
        "attachments": [
            {
                "filename": row["pdf_storage_path"],
                "content": base64.b64encode(pdf_bytes).decode("ascii"),
            }
        ],
    }
    provider_id = _send_via_resend(payload, api_key)
    return EmailResult(
        to=recipient,
        certificate_id=row["certificate_id"],
        provider_id=provider_id,
        sent=True,
    )
