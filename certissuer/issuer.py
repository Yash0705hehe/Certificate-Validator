"""Issuance orchestration — the end-to-end upstream flow.

Given participant details this module:

  1. resolves course metadata and normalizes the completion timestamp,
  2. mints a unique certificate ID (retrying on the unlikely collision),
  3. computes the integrity hash the verifier will recompute,
  4. renders the certificate PDF,
  5. uploads the PDF to the private ``certificates`` storage bucket,
  6. inserts the system-of-record row into ``public.certificates``,
  7. reads the row back and re-verifies the hash as a self-check.

Step 7 guarantees we never mint a certificate that the downstream verifier
would reject: if the stored ``completed_at`` string does not reproduce the hash
we wrote, issuance fails and the just-uploaded PDF is cleaned up.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import config
from .client import get_service_client
from .hashing import generate_cert_hash
from .ids import new_certificate_id
from .pdf import render_certificate_pdf
from .timeutil import normalize_completed_at, to_iso

# How many times to retry ID generation if the random ID already exists.
_MAX_ID_ATTEMPTS = 5


@dataclass
class IssuanceInput:
    candidate_name: str
    candidate_email: str
    course: str
    company: str | None = None
    # Optional; None -> now. Accepts YYYY-MM-DD or a full ISO datetime.
    completed_at: str | None = None


@dataclass
class IssuanceResult:
    certificate_id: str
    candidate_name: str
    candidate_email: str
    company: str | None
    course: str
    course_code: str
    content_version: str
    completed_at: str
    cert_hash: str
    pdf_storage_path: str
    status: str


def _clean(value: str) -> str:
    """Collapse surrounding whitespace; used for the name/company/email inputs
    so the stored value (and therefore the hash) is stable."""
    return " ".join(value.split())


def _reserve_certificate_id(supabase, course_code: str) -> str:
    """Return a certificate ID that is not already present in the table."""
    for _ in range(_MAX_ID_ATTEMPTS):
        candidate = new_certificate_id(course_code)
        existing = (
            supabase.table("certificates")
            .select("certificate_id")
            .eq("certificate_id", candidate)
            .execute()
        )
        if not existing.data:
            return candidate
    raise RuntimeError(
        "Could not generate a unique certificate_id after "
        f"{_MAX_ID_ATTEMPTS} attempts (unexpected — check the database)."
    )


def build_record(data: IssuanceInput) -> dict:
    """Compute all derived fields (ID, hash, paths) without touching the network.

    Shared by the real issuance path and ``--dry-run`` so both produce an
    identical record. Note: because a unique ID cannot be reserved offline,
    dry-run IDs are random and not collision-checked against the database.
    """
    name = _clean(data.candidate_name)
    email = _clean(data.candidate_email)
    company = _clean(data.company) if data.company else None

    meta = config.course_meta(data.course)
    completed_dt = normalize_completed_at(data.completed_at)
    completed_iso = to_iso(completed_dt)

    certificate_id = new_certificate_id(meta.course_code)
    cert_hash = generate_cert_hash(
        name, email, data.course, completed_iso, certificate_id
    )

    return {
        "certificate_id": certificate_id,
        "candidate_name": name,
        "candidate_email": email,
        "company": company,
        "course": data.course,
        "course_code": meta.course_code,
        "content_version": meta.content_version,
        "completed_at": completed_iso,
        "cert_hash": cert_hash,
        "pdf_storage_path": f"{certificate_id}.pdf",
        "status": "active",
        "_completed_dt": completed_dt,  # internal, stripped before insert
        "_course_title": meta.title,  # internal, stripped before insert
    }


def issue_certificate(data: IssuanceInput) -> IssuanceResult:
    """Run the full issuance flow against Supabase and return the stored record."""
    meta = config.course_meta(data.course)
    supabase = get_service_client()

    name = _clean(data.candidate_name)
    email = _clean(data.candidate_email)
    company = _clean(data.company) if data.company else None
    completed_dt = normalize_completed_at(data.completed_at)
    completed_iso = to_iso(completed_dt)

    certificate_id = _reserve_certificate_id(supabase, meta.course_code)
    cert_hash = generate_cert_hash(
        name, email, data.course, completed_iso, certificate_id
    )
    pdf_path = f"{certificate_id}.pdf"

    # 4. Render the PDF.
    pdf_bytes = render_certificate_pdf(
        candidate_name=name,
        course_title=meta.title,
        course=data.course,
        completed_at=completed_dt,
        certificate_id=certificate_id,
        company=company,
    )

    # 5. Upload to the private storage bucket (upsert so a re-run is safe).
    supabase.storage.from_(config.STORAGE_BUCKET).upload(
        path=pdf_path,
        file=pdf_bytes,
        file_options={"content-type": "application/pdf", "upsert": "true"},
    )

    # 6. Insert the system-of-record row. issued_at / created_at default in DB.
    record = {
        "certificate_id": certificate_id,
        "candidate_name": name,
        "candidate_email": email,
        "company": company,
        "course": data.course,
        "course_code": meta.course_code,
        "content_version": meta.content_version,
        "completed_at": completed_iso,
        "cert_hash": cert_hash,
        "pdf_storage_path": pdf_path,
        "status": "active",
    }
    try:
        supabase.table("certificates").insert(record).execute()
    except Exception:
        _cleanup_pdf(supabase, pdf_path)
        raise

    # 7. Read back and re-verify the hash from the stored completed_at.
    stored = (
        supabase.table("certificates")
        .select("*")
        .eq("certificate_id", certificate_id)
        .single()
        .execute()
    )
    row = stored.data
    recomputed = generate_cert_hash(
        row["candidate_name"],
        row["candidate_email"],
        row["course"],
        row["completed_at"],
        row["certificate_id"],
    )
    if recomputed != row["cert_hash"]:
        raise RuntimeError(
            "Post-insert integrity self-check FAILED for "
            f"{certificate_id}: the stored completed_at "
            f"({row['completed_at']!r}) does not reproduce the stored hash. "
            "This certificate would not verify downstream. Investigate before "
            "issuing again."
        )

    return IssuanceResult(
        certificate_id=row["certificate_id"],
        candidate_name=row["candidate_name"],
        candidate_email=row["candidate_email"],
        company=row.get("company"),
        course=row["course"],
        course_code=row["course_code"],
        content_version=row["content_version"],
        completed_at=row["completed_at"],
        cert_hash=row["cert_hash"],
        pdf_storage_path=row["pdf_storage_path"],
        status=row["status"],
    )


def _cleanup_pdf(supabase, pdf_path: str) -> None:
    """Best-effort removal of an uploaded PDF when the insert fails."""
    try:
        supabase.storage.from_(config.STORAGE_BUCKET).remove([pdf_path])
    except Exception:
        pass
