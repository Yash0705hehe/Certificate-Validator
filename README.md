# AA Impact — Certificate Issuance (upstream)

Upstream half of the AA Impact certificate system. You provide participant
details; this mints a **unique certificate ID**, computes the integrity hash the
public verifier recomputes, renders a certificate **PDF**, uploads it to
Supabase Storage, and writes the system-of-record row into `public.certificates`.

The **downstream** half — the public `validate-certificate` /
`verify-certificate` Supabase Edge Functions — is already deployed and reads the
rows this tool writes.

```
 participant details ──▶ issue_certificate.py ──┬─▶ certificates table (system of record)
   (CLI / GitHub Action)                        ├─▶ certificates storage bucket (<id>.pdf)
                                                └─▶ unique certificate_id + SHA-256 integrity hash
                                                        │
 public visitor ──▶ validate-certificate / verify-certificate Edge Function ◀┘  (downstream)
```

## How it works

For each issuance:

1. **Course metadata** (`course_code`, `content_version`) is resolved from
   `certissuer/config.py`.
2. **Completion time** is normalized to whole-second UTC precision (see below).
3. A **unique certificate ID** `AAI-<course_code>-<16 hex>` is minted
   (e.g. `AAI-GHG-CA-ab7d481671fd2198`) and checked against the table.
4. The **integrity hash** is computed:
   `SHA-256(name | email | course | completed_at | certificate_id)`.
5. The **PDF** is rendered and uploaded to the private `certificates` bucket as
   `<certificate_id>.pdf`.
6. The **row** is inserted into `public.certificates`.
7. A **post-insert self-check** reads the row back and re-verifies the hash, so a
   certificate that could not be verified downstream is never left in place.

### The hash contract (important)

The verifier recomputes the exact same SHA-256 over the exact same fields, so
`certissuer/hashing.py` must stay byte-for-byte identical to the Edge Functions'
`recomputeHash()`. `tests/test_hashing.py` pins this to a **real, live
certificate hash** — if it fails, issuance has drifted from the verifier and new
certificates would falsely report as tampered. The completion timestamp is the
one field where formatting could drift, so issuance pins it to **whole-second**
precision (no fractional seconds for Postgres to trim), guaranteeing the stored
string reproduces the hash.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then fill in SUPABASE_SERVICE_ROLE_KEY
```

`SUPABASE_SERVICE_ROLE_KEY` is required — writing to `certificates` and the
private storage bucket needs the service role. **Never commit it.** Find it in
Supabase Dashboard → Project Settings → API → `service_role`.

## Usage

Preview (no writes) — computes ID/hash and renders the PDF locally:

```bash
python issue_certificate.py \
  --name "Test User" --email test@example.com \
  --course GHG --dry-run --pdf-out preview.pdf
```

Issue a real certificate:

```bash
python issue_certificate.py \
  --name "Priya Sharma" \
  --email "priya.sharma@example.com" \
  --company "Example Manufacturing Pvt Ltd" \
  --course GHG \
  --completed-at 2026-07-15
```

Options: `--company` (optional), `--completed-at` (`YYYY-MM-DD` or full ISO
datetime; defaults to now), `--json`, `--dry-run`, `--pdf-out`.

### Via GitHub Actions

`.github/workflows/issue-certificate.yml` provides a manual **Run workflow**
form (name / email / company / course / date). Add two repository secrets first:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

## Courses

| `--course`          | course_code  | status                          |
| ------------------- | ------------ | ------------------------------- |
| `GHG`               | `GHG-CA`     | ✅ confirmed (matches DB)        |
| `Nature`            | `NAT-CA`     | ⚠️ **placeholder — confirm**    |
| `GHG_Nature_Bundle` | `GHGNAT-CA`  | ⚠️ **placeholder — confirm**    |

Only `GHG` records exist in the registry today, so only its `course_code` is
verified. `Nature` and `GHG_Nature_Bundle` codes in `certissuer/config.py` are
best guesses; issuing them prints a warning. **Confirm the real codes with the
team and update `config.py` before issuing those courses in production.**

## Tests

```bash
pip install pytest && python -m pytest tests/ -q
```

## Layout

```
issue_certificate.py            CLI entry point
certissuer/
  config.py                     course metadata, ID prefix, bucket name
  hashing.py                    integrity hash (contract with the verifier)
  ids.py                        certificate ID generation
  timeutil.py                   completed_at normalization
  pdf.py                        certificate PDF (placeholder layout)
  client.py                     Supabase service-role client factory
  issuer.py                     end-to-end issuance orchestration
tests/test_hashing.py           locks the hash to a live certificate
.github/workflows/issue-certificate.yml   manual issuance workflow
```
