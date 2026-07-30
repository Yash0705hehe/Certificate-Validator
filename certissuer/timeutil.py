"""Completion-timestamp handling.

The integrity hash is computed over ``completed_at`` *as a string*, and the
verifier recomputes it from the value PostgREST returns for that column. So the
ISO string we hash must be byte-for-byte identical to what the database returns
after the insert.

Postgres ``timestamptz`` preserves microseconds but trims trailing zeros on
output (``.100000`` comes back as ``.1``). If we hashed a locally-formatted
string with trailing zeros, the round-trip would differ and verification would
fail. We avoid the whole class of problem by pinning issuance timestamps to
**whole-second** precision: with no fractional part there is nothing to trim,
so ``datetime.isoformat()`` and the PostgREST output are guaranteed equal.

The `issuer` module additionally reads the row back after insert and re-checks
the hash, so any residual formatting surprise fails loudly instead of minting a
certificate that cannot be verified.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalize_completed_at(value: str | None) -> datetime:
    """Parse a user-supplied completion time into a whole-second UTC datetime.

    Accepts:
      * ``None`` / empty  -> current time (UTC)
      * ``"YYYY-MM-DD"``  -> that calendar day at 12:00:00 UTC. Noon UTC is the
        same calendar day in America/New_York, so the printed date and the UTC
        date agree and the verifier matches on either.
      * any ISO-8601 datetime (``Z`` or offset accepted; naive is treated UTC)

    Microseconds are always dropped so the stored string round-trips unchanged.
    """
    if value is None or not value.strip():
        dt = datetime.now(timezone.utc)
    else:
        raw = value.strip()
        if _DATE_ONLY.match(raw):
            dt = datetime.fromisoformat(f"{raw}T12:00:00+00:00")
        else:
            # Python <3.11 fromisoformat doesn't accept a trailing 'Z'.
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0)


def to_iso(dt: datetime) -> str:
    """ISO-8601 string exactly as it will be stored/returned (e.g.
    ``2026-07-30T12:00:00+00:00``)."""
    return dt.isoformat()


def _in_display_tz(dt: datetime):
    """Return dt converted to the display timezone (or UTC if tz data missing)."""
    from .config import DISPLAY_TZ

    try:
        from zoneinfo import ZoneInfo

        return dt.astimezone(ZoneInfo(DISPLAY_TZ))
    except Exception:
        return dt


def calendar_day(dt: datetime) -> str:
    """``YYYY-MM-DD`` completion day in the display timezone.

    This is the value the verifier matches on and that is embedded in the QR
    code, so the printed date and the QR agree.
    """
    return _in_display_tz(dt).strftime("%Y-%m-%d")


def display_date(dt: datetime) -> str:
    """Human-readable completion date, e.g. ``10 July 2026``."""
    local = _in_display_tz(dt)
    # %-d is not portable; strip a possible leading zero manually.
    return local.strftime("%d %B %Y").lstrip("0")
