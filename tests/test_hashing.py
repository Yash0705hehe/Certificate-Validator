"""Regression tests that lock the issuance hash to the downstream verifier.

The expected digest below is the ACTUAL ``cert_hash`` stored for a live,
verifiable certificate. If this test ever fails, issuance has drifted from the
Edge Functions' ``recomputeHash()`` and every new certificate would be reported
as tampered — do not "update the expected value" without understanding why.
"""

from certissuer.hashing import generate_cert_hash
from certissuer.timeutil import normalize_completed_at, to_iso


def test_matches_live_certificate_hash():
    # Live record: AAI-GHG-CA-ab7d481671fd2198 (Priya Sharma).
    digest = generate_cert_hash(
        "Priya Sharma",
        "priya.sharma@example.com",
        "GHG",
        "2026-07-10T11:15:56.068403+00:00",
        "AAI-GHG-CA-ab7d481671fd2198",
    )
    assert digest == "fa0a84ec207f0c9522a8aa4049a3784e0f5043b87e3fecc2d0909a408e678fba"


def test_completed_at_whole_second_round_trips():
    # Whole-second precision means no fractional part for Postgres to trim,
    # so the string we hash equals the string PostgREST returns.
    dt = normalize_completed_at("2026-07-15")
    assert to_iso(dt) == "2026-07-15T12:00:00+00:00"

    dt2 = normalize_completed_at("2026-07-15T04:41:02.844378+00:00")
    assert to_iso(dt2) == "2026-07-15T04:41:02+00:00"  # microseconds dropped
