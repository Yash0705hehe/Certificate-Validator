---
name: issue-certificate
description: Issue an AA Impact training certificate for a participant. Use when the user wants to create/issue/generate a certificate or "add a name" to the registry, and provides participant details (name, email, course). Triggers on requests like "issue a certificate for …", "add a certificate for …", "generate a GHG certificate for …", or the /issue-certificate command.
---

# Issue an AA Impact certificate

This skill issues a real certificate for a participant: it creates the
system-of-record row in the `certificates` table **and** the branded PDF in the
private `certificates` storage bucket, then confirms the result.

It works by dispatching the repository's `issue-certificate.yml` GitHub Actions
workflow, which runs `issue_certificate.py` with the Supabase service-role key
(stored as a repo secret). That is the only path that can produce both the DB
record and the PDF — this chat environment has neither the service key nor
network access to Supabase for storage uploads.

## Prerequisites (verify once; tell the user if missing)

- Repo secrets `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are set (Settings →
  Secrets and variables → Actions). If issuance fails auth, this is why.
- The `issue-certificate.yml` workflow exists on the repo's default branch.
- GitHub MCP tools (`mcp__github__*`) and Supabase MCP tools
  (`mcp__Supabase__*`) are available in the session.

Repo coordinates: owner `yash0705hehe`, repo `certificate-validator`.
Supabase project id: `ukhzxqxugzqcfqcwnmvu`.

## Step 1 — Collect the details

Required:
- **name** — participant full name
- **email** — participant email
- **course** — one of `GHG`, `Nature`, `GHG_Nature_Bundle`

Optional:
- **company**
- **completed_at** — `YYYY-MM-DD` (defaults to today if omitted)

Parse these from what the user gave you. If any **required** field is missing or
ambiguous, ask for it (use AskUserQuestion for `course`). Do not guess a name or
email.

## Step 2 — Validate and confirm

- Reject a `course` not in the allowed set.
- If `course` is not `GHG`, warn: only GHG's course code and certificate copy are
  confirmed; `Nature` / `GHG_Nature_Bundle` are placeholders (see
  `certissuer/config.py`) — ask the user to confirm they still want to proceed.
- Echo the exact details you're about to issue (name, email, company, course,
  completion date) in one line and proceed. Issuing writes a permanent,
  outward-facing record, so if anything looks off, confirm before dispatching.

## Step 3 — Dispatch the issuance workflow

Call `mcp__github__actions_run_trigger`:
- `method`: `run_workflow`
- `owner`: `yash0705hehe`, `repo`: `certificate-validator`
- `workflow_id`: `issue-certificate.yml`
- `ref`: the repo's default branch (currently
  `claude/upstream-certificate-generation-0m203i` — confirm with
  `mcp__github__list_branches` if unsure)
- `inputs`: `{ name, email, company, course, completed_at }` (pass empty strings
  for omitted optionals)

## Step 4 — Wait for it to finish

Poll `mcp__github__actions_list` (`method: list_workflow_runs`, `resource_id:
issue-certificate.yml`, `workflow_runs_filter.event: workflow_dispatch`) for the
newest run, then `mcp__github__actions_get` (`get_workflow_run`) until
`status = completed`. A run takes ~1–2 minutes (it installs Chromium). Do not
busy-wait with shell sleeps — space out the polls.

- `conclusion = success` → continue to Step 5.
- `conclusion = failure` → read the failing job log
  (`mcp__github__actions_list` → `list_workflow_jobs`, then the run logs) and
  report the real error (most likely a missing/invalid secret). Do not claim
  success.

## Step 5 — Confirm the record and report

Query the database to fetch the row the run just created:

```sql
select certificate_id, candidate_name, course, completed_at, pdf_storage_path, status
from certificates
where candidate_email = '<email>'
order by created_at desc
limit 1;
```

via `mcp__Supabase__execute_sql` (project `ukhzxqxugzqcfqcwnmvu`).

Report to the user:
- the new **certificate_id**,
- how to **validate** it: on the validator, enter that ID + the completion date
  (matching is case-insensitive), or ID + the participant's name,
- where the **PDF** lives: Storage → `certificates` bucket → `<certificate_id>.pdf`.

## Notes

- Certificate ID format is `AAI-<course_code>-<16 hex>`; it is minted uniquely
  by the workflow — never invent one.
- The certificate is a real `active` record. To undo a mistaken issuance, set its
  `status` to `revoked` (do not delete — the table is insert-only by design).
- This skill issues **one** certificate per invocation. For several, dispatch
  once per participant.
