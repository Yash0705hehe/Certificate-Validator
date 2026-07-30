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


@dataclass(frozen=True)
class CourseMeta:
    """Static metadata attached to an issued certificate for a course."""

    # Human-facing course title used on the certificate PDF.
    title: str
    # Stored in certificates.course_code.
    course_code: str
    # Stored in certificates.content_version.
    content_version: str
    # True once the course_code / content_version are verified against the
    # real registry. Issuing an unconfirmed course prints a warning.
    confirmed: bool


# Keys MUST match the certificates.course CHECK constraint:
#   ('GHG', 'Nature', 'GHG_Nature_Bundle')
COURSE_METADATA: dict[str, CourseMeta] = {
    "GHG": CourseMeta(
        title="Greenhouse Gas (GHG) Accounting",
        course_code="GHG-CA",
        content_version="v1.0-2026-07-08",
        confirmed=True,  # matches every existing record in the database
    ),
    "Nature": CourseMeta(
        title="Nature & Biodiversity Accounting",
        course_code="NAT-CA",
        content_version="v1.0-2026-07-08",
        confirmed=False,  # PLACEHOLDER — confirm course_code before issuing
    ),
    "GHG_Nature_Bundle": CourseMeta(
        title="GHG & Nature Accounting (Bundle)",
        course_code="GHGNAT-CA",
        content_version="v1.0-2026-07-08",
        confirmed=False,  # PLACEHOLDER — confirm course_code before issuing
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
