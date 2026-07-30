"""Integrity hash — the contract with the downstream verifier.

The public `validate-certificate` / `verify-certificate` Edge Functions
recompute this exact hash from the stored certificate fields to prove the
record was not altered. If this function and the Edge Functions ever disagree
by a single byte, every certificate will falsely report as "tampered".

The payload and digest MUST stay identical to the Edge Functions'
``recomputeHash()``:

    payload = `${candidate_name}|${candidate_email}|${course}|${completed_at}|${certificate_id}`
    digest  = SHA-256 hex (lowercase)

``completed_at`` here is the ISO-8601 string exactly as it is stored in (and
returned by PostgREST from) the ``certificates.completed_at`` column. See
:func:`certissuer.timeutil.normalize_completed_at` for why we pin whole-second
precision so the string round-trips through Postgres unchanged.
"""

from __future__ import annotations

import hashlib

# Field separator used in the hash payload. Must match the Edge Functions.
_SEP = "|"


def generate_cert_hash(
    candidate_name: str,
    candidate_email: str,
    course: str,
    completed_at_iso: str,
    certificate_id: str,
) -> str:
    """Return the lowercase SHA-256 hex digest for a certificate record.

    Every argument must be the *exact* value stored in the corresponding
    ``certificates`` column — same casing, same whitespace, and for
    ``completed_at_iso`` the same ISO string PostgREST returns.
    """
    payload = _SEP.join(
        [
            candidate_name,
            candidate_email,
            course,
            completed_at_iso,
            certificate_id,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
