"""Issuance configuration and course metadata.

Values here are derived from the live ``certificates`` records and the schema
CHECK constraints. Only the ``GHG`` row currently exists in the database, so
its ``course_code`` / ``content_version`` are *confirmed*. The ``Nature`` and
``GHG_Nature_Bundle`` entries are sensible placeholders — confirm them with the
team before issuing certificates for those courses (see README).
"""

from __future__ import annotations

from dataclasses import dataclass

# Prefix on every certificate ID: AAI-<course_code>-<16 hex chars>.
CERT_ID_PREFIX = "AAI"

# Number of random bytes in the certificate ID suffix. 8 bytes -> 16 hex chars,
# matching the existing IDs (e.g. AAI-GHG-CA-ab7d481671fd2198) and giving 64
# bits of entropy (collision probability is negligible).
CERT_ID_RANDOM_BYTES = 8

# Private Supabase Storage bucket that holds the certificate PDFs. The stored
# ``pdf_storage_path`` is "<certificate_id>.pdf" relative to this bucket.
STORAGE_BUCKET = "certificates"

# Timezone the human-readable completion date is presented in on the website /
# certificate. The verifier accepts a match on either this zone's day or the
# UTC day, so pinning issuance to noon UTC (see timeutil) keeps them identical.
DISPLAY_TZ = "America/New_York"


# Base URL of the deployed Supabase Edge Functions (verification endpoints).
SUPABASE_FUNCTIONS_BASE = (
    "https://ukhzxqxugzqcfqcwnmvu.supabase.co/functions/v1"
)

# Template used to build the QR code target printed on the certificate. It is
# scanned to verify the credential. Overridable via the CERT_VERIFY_URL env var
# (point it at your public validator page if you have one). Available
# placeholders: {certificate_id} and {date} (the completion calendar day).
DEFAULT_VERIFY_URL_TEMPLATE = (
    SUPABASE_FUNCTIONS_BASE
    + "/validate-certificate?certificate_id={certificate_id}&date={date}"
)


@dataclass(frozen=True)
class CourseMeta:
    """Static metadata attached to an issued certificate for a course.

    The first four fields are stored in / validated against the database. The
    remaining fields are purely presentational — they fill the course-specific
    slots in the certificate template (sidebar, banner, seal, blurb).
    """

    # Human-facing course title (used in CLI messages / logs).
    title: str
    # Stored in certificates.course_code.
    course_code: str
    # Stored in certificates.content_version.
    content_version: str
    # True once the course_code / content_version and the presentational copy
    # below are verified against the real registry. Issuing an unconfirmed
    # course prints a warning.
    confirmed: bool
    # --- certificate template copy (HTML fragments allowed) ---
    # Navy sidebar course name (may include <br> / &amp;).
    sidebar: str
    # Sidebar "LEVEL" value, e.g. "Intermediate".
    level: str
    # Gold banner under the course title.
    banner: str
    # Small subjects/topics line under the banner.
    subjects: str
    # Descriptive blurb paragraph.
    description: str

    @property
    def seal_code(self) -> str:
        """Code shown in the round seal — the course code."""
        return self.course_code


# Keys MUST match the certificates.course CHECK constraint:
#   ('GHG', 'Nature', 'GHG_Nature_Bundle')
COURSE_METADATA: dict[str, CourseMeta] = {
    # Confirmed against every existing record and the provided certificate.
    "GHG": CourseMeta(
        title="Greenhouse Gas (GHG) Accounting",
        course_code="GHG-CA",
        content_version="v1.0-2026-07-08",
        confirmed=True,
        sidebar="GHG Accounting<br>&amp; Reporting Training",
        level="Intermediate",
        banner="GHG ACCOUNTING &amp; REPORTING TRAINING",
        subjects="INTERMEDIATE LEVEL · GWP &amp; EMISSION FACTORS · SCOPE 1 &amp; 2 · SCOPE 3",
        description=(
            "Content is referenced against the GHG Protocol Corporate "
            "Accounting and Reporting Standard and ISO 14064-1:2018, at a "
            "foundational-to-intermediate depth."
        ),
    ),
    # PLACEHOLDER copy — confirm course_code and all presentational text
    # before issuing Nature certificates in production.
    "Nature": CourseMeta(
        title="Nature & Biodiversity Accounting",
        course_code="NAT-CA",
        content_version="v1.0-2026-07-08",
        confirmed=False,
        sidebar="Nature &amp; Biodiversity<br>Accounting Training",
        level="Intermediate",
        banner="NATURE &amp; BIODIVERSITY ACCOUNTING TRAINING",
        subjects="INTERMEDIATE LEVEL · TNFD · BIODIVERSITY METRICS",
        description=(
            "Content is referenced against the TNFD recommendations and "
            "related nature-accounting frameworks, at a foundational-to-"
            "intermediate depth."
        ),
    ),
    # PLACEHOLDER copy — confirm before issuing bundle certificates.
    "GHG_Nature_Bundle": CourseMeta(
        title="GHG & Nature Accounting (Bundle)",
        course_code="GHGNAT-CA",
        content_version="v1.0-2026-07-08",
        confirmed=False,
        sidebar="GHG &amp; Nature<br>Accounting Training",
        level="Intermediate",
        banner="GHG &amp; NATURE ACCOUNTING TRAINING",
        subjects="INTERMEDIATE LEVEL · GHG PROTOCOL · TNFD · SCOPE 1–3",
        description=(
            "Combined programme referenced against the GHG Protocol, "
            "ISO 14064-1:2018 and the TNFD recommendations, at a "
            "foundational-to-intermediate depth."
        ),
    ),
}

# The set of courses the certificates.course CHECK constraint accepts.
VALID_COURSES = tuple(COURSE_METADATA.keys())


def course_meta(course: str) -> CourseMeta:
    """Look up metadata for a course, raising a clear error for unknown ones."""
    try:
        return COURSE_METADATA[course]
    except KeyError:
        raise ValueError(
            f"Unknown course {course!r}. Valid courses: {', '.join(VALID_COURSES)}"
        ) from None
