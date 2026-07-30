"""QR-code generation for the certificate's "scan to verify" mark.

Produces a self-contained SVG ``data:`` URI (no network, crisp at any size)
using segno. The encoded target is built from the verify-URL template so it can
be pointed at a public validator page instead of the raw Edge Function.
"""

from __future__ import annotations

import base64
import os
from io import BytesIO
from urllib.parse import quote

import segno

from .config import DEFAULT_VERIFY_URL_TEMPLATE


def verification_url(certificate_id: str, date: str) -> str:
    """Build the URL the QR code points to for this certificate.

    Overridable with the ``CERT_VERIFY_URL`` env var (a template that may use
    ``{certificate_id}`` and ``{date}`` placeholders).
    """
    template = os.environ.get("CERT_VERIFY_URL", DEFAULT_VERIFY_URL_TEMPLATE)
    return template.format(
        certificate_id=quote(certificate_id, safe=""),
        date=quote(date, safe=""),
    )


def qr_data_uri(payload: str) -> str:
    """Return an ``image/svg+xml`` data URI encoding ``payload``."""
    qr = segno.make(payload, error="m")
    buf = BytesIO()
    # Tight, quiet-zone-1 SVG scaled by the container; dark = brand navy.
    qr.save(buf, kind="svg", border=1, dark="#1c2b4a", light="#ffffff", xmldecl=False)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return "data:image/svg+xml;base64," + b64
