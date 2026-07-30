"""Certificate PDF rendering (placeholder layout).

This is a clean, self-contained placeholder design so the end-to-end pipeline
works today. Real branding / an official template can be dropped in later by
editing :func:`render_certificate_pdf` — nothing else in the pipeline needs to
change, because the ID/hash/DB contract is independent of the visual layout.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from .config import DISPLAY_TZ

_PAGE = landscape(A4)
_WIDTH, _HEIGHT = _PAGE

# Placeholder palette — swap for real brand colors with the template.
_INK = colors.HexColor("#1f2933")
_ACCENT = colors.HexColor("#0b7285")
_MUTED = colors.HexColor("#6b7280")


def _display_date(dt: datetime) -> str:
    """Human-readable completion date, e.g. '15 July 2026'.

    Rendered in the display timezone so the printed date matches what the
    verifier accepts.
    """
    try:
        from zoneinfo import ZoneInfo

        local = dt.astimezone(ZoneInfo(DISPLAY_TZ))
    except Exception:
        # zoneinfo/tzdata unavailable — fall back to UTC. Noon-UTC issuance
        # keeps the calendar day identical either way.
        local = dt
    return local.strftime("%d %B %Y")


def render_certificate_pdf(
    *,
    candidate_name: str,
    course_title: str,
    course: str,
    completed_at: datetime,
    certificate_id: str,
    company: str | None = None,
) -> bytes:
    """Render a one-page certificate PDF and return the raw bytes."""
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=_PAGE)
    c.setTitle(f"AA Impact Certificate — {certificate_id}")
    c.setAuthor("AA Impact Inc.")

    cx = _WIDTH / 2

    # Decorative double border.
    c.setStrokeColor(_ACCENT)
    c.setLineWidth(3)
    c.rect(12 * mm, 12 * mm, _WIDTH - 24 * mm, _HEIGHT - 24 * mm)
    c.setLineWidth(0.75)
    c.rect(16 * mm, 16 * mm, _WIDTH - 32 * mm, _HEIGHT - 32 * mm)

    # Issuer.
    c.setFillColor(_ACCENT)
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(cx, _HEIGHT - 40 * mm, "AA IMPACT INC.")

    # Title.
    c.setFillColor(_INK)
    c.setFont("Helvetica", 26)
    c.drawCentredString(cx, _HEIGHT - 62 * mm, "Certificate of Completion")

    c.setFillColor(_MUTED)
    c.setFont("Helvetica", 13)
    c.drawCentredString(cx, _HEIGHT - 76 * mm, "This is to certify that")

    # Recipient name.
    c.setFillColor(_INK)
    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(cx, _HEIGHT - 96 * mm, candidate_name)

    if company:
        c.setFillColor(_MUTED)
        c.setFont("Helvetica-Oblique", 12)
        c.drawCentredString(cx, _HEIGHT - 106 * mm, company)

    # Course line.
    c.setFillColor(_MUTED)
    c.setFont("Helvetica", 13)
    c.drawCentredString(
        cx, _HEIGHT - 122 * mm, "has successfully completed the training"
    )
    c.setFillColor(_ACCENT)
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(cx, _HEIGHT - 134 * mm, course_title)

    c.setFillColor(_MUTED)
    c.setFont("Helvetica", 12)
    c.drawCentredString(
        cx, _HEIGHT - 146 * mm, f"Completed on {_display_date(completed_at)}"
    )

    # Certificate ID footer — the value used for public verification.
    c.setFillColor(_INK)
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(cx, 30 * mm, f"Certificate ID:  {certificate_id}")
    c.setFillColor(_MUTED)
    c.setFont("Helvetica", 9)
    c.drawCentredString(
        cx,
        23 * mm,
        "Verify this certificate at the AA Impact website using the "
        "Certificate ID and completion date.",
    )

    c.showPage()
    c.save()
    return buf.getvalue()
