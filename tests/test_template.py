"""Template substitution tests (no browser needed).

Guards that every token is filled, user input is HTML-escaped, and the QR code
is embedded — so a rendering regression is caught without launching Chromium.
"""

import re
from datetime import datetime, timezone

from certissuer import config
from certissuer.pdf import build_certificate_html


def _html():
    return build_certificate_html(
        recipient_name="Priya Sharma",
        certificate_id="AAI-GHG-CA-ab7d481671fd2198",
        completed_at=datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc),
        course=config.course_meta("GHG"),
    )


def test_no_tokens_left_unreplaced():
    html = _html()
    leftover = re.findall(r"\{\{[A-Z_]+\}\}", html)
    assert not leftover, f"unreplaced tokens: {leftover}"


def test_values_present():
    html = _html()
    assert "Priya Sharma" in html
    assert "AAI-GHG-CA-ab7d481671fd2198" in html
    assert "15 July 2026" in html  # display date in America/New_York
    assert "GHG ACCOUNTING &amp; REPORTING TRAINING" in html
    assert "data:image/svg+xml;base64," in html  # QR embedded


def test_recipient_name_is_escaped():
    html = build_certificate_html(
        recipient_name="<script>alert(1)</script>",
        certificate_id="AAI-GHG-CA-0000000000000000",
        completed_at=datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc),
        course=config.course_meta("GHG"),
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
