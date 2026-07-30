"""Certificate PDF rendering.

Renders the AA Impact "Certificate of Achievement" HTML template (a fixed
1120x784 layout with inlined web fonts) to a pixel-faithful PDF using a headless
Chromium via Playwright. Rendering the real HTML — rather than redrawing the
design — keeps the output identical to the approved certificate artifact.

The dynamic fields (recipient name, certificate ID, completion date, QR code)
and the course-specific copy are substituted into the template's tokens.
"""

from __future__ import annotations

import html as html_lib
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from .config import CourseMeta
from .timeutil import display_date

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "certificate.html"

# Certificate page geometry (must match the template's @page / root div).
PAGE_WIDTH_PX = 1120
PAGE_HEIGHT_PX = 784

# Candidate Chromium executables. Env override wins; then the pre-provisioned
# browser in this environment; then let Playwright resolve its own download.
_CHROMIUM_CANDIDATES = [
    os.environ.get("CHROMIUM_EXECUTABLE"),
    "/opt/pw-browsers/chromium",  # symlink to the pre-provisioned chrome binary
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
]


@lru_cache(maxsize=1)
def _template() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def _resolve_executable() -> str | None:
    for path in _CHROMIUM_CANDIDATES:
        if path and Path(path).exists():
            return path
    return None  # fall back to Playwright's bundled/downloaded browser


def build_certificate_html(
    *,
    recipient_name: str,
    certificate_id: str,
    completed_at: datetime,
    course: CourseMeta,
) -> str:
    """Substitute all tokens and return the final, self-contained HTML.

    The QR code in the design is a static image baked into the template; it is
    not generated per certificate.
    """
    tokens = {
        # User / record values are HTML-escaped.
        "{{RECIPIENT_NAME}}": html_lib.escape(recipient_name),
        "{{CERTIFICATE_ID}}": html_lib.escape(certificate_id),
        "{{ISSUE_DATE}}": html_lib.escape(display_date(completed_at)),
        # Course copy is trusted config and may contain intended HTML (<br>, &amp;).
        "{{COURSE_SIDEBAR}}": course.sidebar,
        "{{LEVEL}}": course.level,
        "{{COURSE_BANNER}}": course.banner,
        "{{COURSE_SUBJECTS}}": course.subjects,
        "{{COURSE_DESCRIPTION}}": course.description,
        "{{SEAL_CODE}}": html_lib.escape(course.seal_code),
    }
    doc = _template()
    for token, value in tokens.items():
        doc = doc.replace(token, value)
    return doc


def render_certificate_pdf(
    *,
    recipient_name: str,
    certificate_id: str,
    completed_at: datetime,
    course: CourseMeta,
) -> bytes:
    """Render the certificate to PDF bytes."""
    from playwright.sync_api import sync_playwright

    doc = build_certificate_html(
        recipient_name=recipient_name,
        certificate_id=certificate_id,
        completed_at=completed_at,
        course=course,
    )

    executable = _resolve_executable()
    with sync_playwright() as p:
        launch_kwargs = {"args": ["--no-sandbox"]}
        if executable:
            launch_kwargs["executable_path"] = executable
        browser = p.chromium.launch(**launch_kwargs)
        try:
            page = browser.new_page()
            page.set_content(doc, wait_until="networkidle")
            # Ensure the inlined web fonts are ready before printing.
            page.evaluate("() => document.fonts.ready")
            pdf = page.pdf(
                width=f"{PAGE_WIDTH_PX}px",
                height=f"{PAGE_HEIGHT_PX}px",
                print_background=True,
                margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            )
        finally:
            browser.close()
    return pdf
