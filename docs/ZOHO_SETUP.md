# Zoho Learn → automatic certificates: credential setup

This wires the daily **Sync Zoho completions** workflow. Once done, learners who
complete a mapped course in Zoho Learn get a certificate issued and emailed
automatically — no manual step.

You'll create a Zoho OAuth client, generate a long-lived **refresh token**, find
your **portal id** and **course id(s)**, and save everything as GitHub secrets.

> Do everything in the account/data center that hosts your Zoho Learn portal.
> Zoho has regional data centers — `.com`, `.in`, `.eu`, `.com.au`, `.jp`. Use
> the matching hosts throughout (examples below use `.com`).

## 1. Create an OAuth client (Self Client)

1. Go to the Zoho API Console: **https://api-console.zoho.com** (use your DC's
   console, e.g. `api-console.zoho.in`).
2. **Add Client → Self Client → Create**.
3. Copy the **Client ID** and **Client Secret**.

## 2. Generate a grant code, then a refresh token

1. In the Self Client, open the **Generate Code** tab.
2. **Scope**: enter a Zoho Learn *read* scope for courses/reports. The console
   lists the available scopes — pick the read scope(s) that cover course
   reports (e.g. `ZohoLearn.courses.READ`; add a reports read scope if listed).
3. **Time duration**: 10 minutes. **Scope Description**: anything. **Create**.
4. Choose your portal and **Create** — copy the **grant code** (valid briefly).
5. Exchange the grant code for tokens (run within the 10 minutes). Replace the
   placeholders and run in a terminal:

   ```bash
   curl -s "https://accounts.zoho.com/oauth/v2/token" \
     -d grant_type=authorization_code \
     -d client_id=YOUR_CLIENT_ID \
     -d client_secret=YOUR_CLIENT_SECRET \
     -d code=YOUR_GRANT_CODE
   ```

   The JSON response contains a **`refresh_token`** — copy it. (The refresh
   token is long-lived; the workflow uses it to mint short-lived access tokens.)

## 3. Find your portal id and course id(s)

- **Portal id** (a.k.a. org id): open Zoho Learn in a browser; it appears in the
  URL / portal settings. It's the value sent as the `orgId` header.
- **Course id**: open the course in Zoho Learn — the id is in the course URL.
  You need one id per course you want to automate.

## 4. Add GitHub repository secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**.
Add each:

| Secret | Value / example |
| --- | --- |
| `ZOHO_ACCOUNTS_DOMAIN` | `accounts.zoho.com` (your DC) |
| `ZOHO_API_DOMAIN` | `learn.zoho.com` (your DC) |
| `ZOHO_CLIENT_ID` | from step 1 |
| `ZOHO_CLIENT_SECRET` | from step 1 |
| `ZOHO_REFRESH_TOKEN` | from step 2 |
| `ZOHO_PORTAL_ID` | from step 3 |
| `ZOHO_COURSE_MAP` | `{"<zoho_course_id>":"GHG"}` (map each course id to `GHG` / `Nature` / `GHG_Nature_Bundle`) |

(The Supabase and Resend secrets from the other workflows must also be set.)

## 5. Validate safely, then let it run

1. Repo → **Actions → Sync Zoho completions → Run workflow**, tick **Dry run**.
   The log lists who *would* get a certificate — nothing is written or emailed.
2. If the log says it couldn't find the learner list, run it once with a dump to
   inspect the real report shape (locally: `python sync_zoho.py --dump`) and
   share it — the field mapping in `certissuer/zoho.py` may need a one-line pin
   to your portal's response.
3. Once the dry run looks right, the daily 06:00 UTC schedule takes over
   automatically. You can also trigger a real run any time (Run workflow without
   dry-run).

## Notes

- **Idempotent**: a learner who already has an active certificate for a course
  is skipped, so re-runs never duplicate or re-email.
- **Completion date**: uses Zoho's completion timestamp when present, otherwise
  the run date.
- If a refresh token is ever revoked (password reset, scope change), repeat
  step 2 and update `ZOHO_REFRESH_TOKEN`.
