"""Certificate ID generation.

Format (matches existing records, e.g. ``AAI-GHG-CA-ab7d481671fd2198``):

    <PREFIX>-<course_code>-<random hex>

The random suffix uses :func:`secrets.token_hex` (cryptographically strong).
The ``certificate_id`` column is UNIQUE, so the real collision guard is the
database constraint; callers additionally re-check for existence and retry to
avoid a failed insert on the astronomically unlikely collision.
"""

from __future__ import annotations

import secrets

from .config import CERT_ID_PREFIX, CERT_ID_RANDOM_BYTES


def new_certificate_id(course_code: str) -> str:
    """Mint a fresh (random) certificate ID for the given course code."""
    suffix = secrets.token_hex(CERT_ID_RANDOM_BYTES)
    return f"{CERT_ID_PREFIX}-{course_code}-{suffix}"
