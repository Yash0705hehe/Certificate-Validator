---
name: email-certificate
description: Email an AA Impact certificate PDF to a recipient. Use when the user wants to "email/send a certificate to someone". Handles two cases — (a) given a person's details (name, email, course), issue the certificate AND email it; (b) given an already-issued certificate ID, just email its PDF. Triggers on "email a certificate to …", "send <name> their certificate", "issue and email a certificate for …", or the /email-certificate command.
---

# Email an AA Impact certificate

Emails a certificate PDF to a recipient. The email is sent from inside a GitHub
Actions workflow (which has the Supabase service-role key and Resend API key);
this chat environment cannot send mail or reach Supabase storage directly.

Two modes — pick based on what the user gives you:

- **Issue + email** — they gave participant details (name, email, course, and
  optionally company / completion date) → create the certificate and email it.
- **Email existing** — they gave a certificate ID (or refer to one already
  issued) → email that certificate's PDF, optionally to a different address.

## Prerequisites (tell the user if missing)

- Repo secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, **`RESEND_API_KEY`**,
  and optionally `RESEND_FROM` (a sender on a Resend-verified domain, e.g.
  `AA Impact Academy <certificates@aaimpactinc.com>`). If email fails, a missing
  `RESEND_API_KEY` or an unverified sender domain is the usual cause.
- GitHub MCP (`mcp__github__*`) and Supabase MCP (`mcp__Supabase__*`) available.

Repo: owner `yash0705hehe`, repo `certificate-validator`. Default branch:
`claude/upstream-certificate-generation-0m203i` (confirm with
`mcp__github__list_branches`). Supabase project: `ukhzxqxugzqcfqcwnmvu`.

## Step 1 — Determine the mode and gather inputs

- If the user supplied a **certificate ID** → *email existing* mode. Required:
  `certificate_id`. Optional: `to` (recipient; defaults to the certificate's own
  candidate email).
- Otherwise, if they supplied **name + email + course** → *issue + email* mode.
  Same required/optional fields as the `issue-certificate` skill
  (name, email, course ∈ {GHG, Nature, GHG_Nature_Bundle}; optional company,
  completed_at `YYYY-MM-DD`). The recipient is the participant email unless they
  name a different address.

If required fields are missing or the mode is ambiguous, ask (use
AskUserQuestion for the mode or the course). Never guess an email address.

## Step 2 — Confirm

Echo what you'll do in one line — e.g. "Issue a GHG certificate for Jane Doe and
email it to jane@acme.com" or "Email certificate AAI-GHG-CA-… to jane@acme.com".
Sending email is outward-facing and hard to unsend, so if anything looks off,
confirm the recipient before dispatching. For a non-GHG course, warn that its
copy is still placeholder (see `certissuer/config.py`).

## Step 3 — Dispatch the right workflow

Use `mcp__github__actions_run_trigger` (`method: run_workflow`, owner
`yash0705hehe`, repo `certificate-validator`, `ref` = default branch).

- **Issue + email** → `workflow_id: issue-certificate.yml`, inputs
  `{ name, email, company, course, completed_at, send_email: true }`.
- **Email existing** → `workflow_id: email-certificate.yml`, inputs
  `{ certificate_id, to }` (`to` empty to use the certificate's own email).

## Step 4 — Wait and verify

Poll `mcp__github__actions_list` (`list_workflow_runs` for that workflow file,
event `workflow_dispatch`) for the newest run, then `mcp__github__actions_get`
(`get_workflow_run`) until `completed`. Space out polls; don't shell-sleep.

- `success` → for issue+email, fetch the new row from the `certificates` table
  (`mcp__Supabase__execute_sql`, newest by that email) to report the
  certificate_id. Tell the user the email was sent, to whom, and the cert ID.
- `failure` → read the failing job log and report the real reason (commonly a
  missing `RESEND_API_KEY` or an unverified Resend sender domain). Do not claim
  the email was sent.

## Notes

- The recipient defaults to the participant's own email; only send elsewhere if
  the user asked.
- Email delivery depends on Resend + a verified sender domain. If the domain
  isn't verified yet, sends will fail — surface that clearly rather than
  retrying.
- To email several people, dispatch once per person.
