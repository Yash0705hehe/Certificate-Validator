# Auto-issue certificates on Zoho Learn course completion

When a learner completes a mapped course, Zoho Learn emails the admin
"*&lt;Learner&gt; has completed course &lt;Course&gt;.*". We use **that email as the
trigger**: a Microsoft 365 **Power Automate** flow catches it and calls GitHub,
which issues + emails the certificate automatically. (Zoho Learn has no public
completion API or Zoho Flow trigger yet, so the email is the reliable signal.)

```
Zoho completion email → Power Automate (filter sender+subject)
   → GitHub repository_dispatch → workflow parses name+course,
     looks up the learner's email from the Zoho roster, issues + emails the cert
```

You set this up once. Two parts: **A) Zoho credentials** (so the workflow can
resolve the learner's email from the roster), and **B) the Power Automate flow**.

---

## Part A — Zoho credentials (GitHub secrets)

These let the workflow call the one Zoho API that works: the course roster
(to turn the learner's *name* from the email into their *email address*).

1. **OAuth client** — https://api-console.zoho.in → **Self Client** → copy
   **Client ID** + **Client Secret**.
2. **Refresh token** — Self Client → **Generate Code** → scope
   `ZohoLearn.course.ALL`, 10 min → copy the grant code, then in a terminal:
   ```
   curl https://accounts.zoho.in/oauth/v2/token -d "grant_type=authorization_code&client_id=YOUR_ID&client_secret=YOUR_SECRET&code=YOUR_CODE"
   ```
   Copy the `refresh_token` from the response.
3. **Portal slug + course id** — from your course URL
   `learn.zoho.in/portal/aa-impact/course/scope-3-quiz`: portal slug is
   `aa-impact`; the course id is `58084000000002174` (already known for the GHG
   course).
4. Add these **GitHub repository secrets** (Settings → Secrets and variables →
   Actions):

   | Secret | Value |
   | --- | --- |
   | `ZOHO_ACCOUNTS_DOMAIN` | `accounts.zoho.in` |
   | `ZOHO_API_DOMAIN` | `learn.zoho.in` |
   | `ZOHO_CLIENT_ID` | from step 1 |
   | `ZOHO_CLIENT_SECRET` | from step 1 |
   | `ZOHO_REFRESH_TOKEN` | from step 2 |
   | `ZOHO_PORTAL` | `aa-impact` |
   | `ZOHO_COURSE_MAP` | `{"GHG Accounting Course": {"id": "58084000000002174", "course": "GHG"}}` |

   (Supabase + Resend secrets from the other workflows must also be set.)

5. **Test it end-to-end** before wiring Power Automate: repo → **Actions → Zoho
   completion → Run workflow**, paste the subject
   `Ananya Mehra has completed course GHG Accounting Course.` and tick **Dry
   run**. The log should resolve Ananya's email from the roster. Untick dry-run
   to actually issue + email.

---

## Part B — Power Automate flow (the trigger)

1. Create a **GitHub token** the flow will use: GitHub → Settings → Developer
   settings → **Personal access tokens → Fine-grained** → Repository access =
   `Yash0705hehe/Certificate-Validator`, Permissions → **Contents: Read and
   write**. Copy the token. (A classic token with the `repo` scope also works.)

2. Go to **make.powerautomate.com** → **Create → Automated cloud flow**.
   - Trigger: **Office 365 Outlook — "When a new email arrives (V3)"**.
   - In the trigger options: **Folder** = Inbox; **From** =
     `noreply@mail.zoholearn.in`; **Subject Filter** = `has completed course`.

3. Add an action: **HTTP** (or "Send an HTTP request"):
   - **Method**: `POST`
   - **URI**: `https://api.github.com/repos/Yash0705hehe/Certificate-Validator/dispatches`
   - **Headers**:
     - `Authorization`: `Bearer YOUR_GITHUB_TOKEN`
     - `Accept`: `application/vnd.github+json`
     - `Content-Type`: `application/json`
     - `User-Agent`: `aa-impact-flow`
   - **Body**:
     ```json
     {
       "event_type": "zoho_completion",
       "client_payload": { "subject": "@{triggerOutputs()?['body/subject']}" }
     }
     ```
     (Use the flow's dynamic content for the email **Subject** in place of the
     `@{...}` expression if you prefer clicking it in.)

4. **Save**, then complete a test course in Zoho (or use the manual dry-run in
   Part A step 5). Within a minute of the completion email arriving, the GitHub
   **Zoho completion** workflow runs and the certificate is issued + emailed.

> **Note:** the HTTP action is a Power Automate *premium* connector. If your
> M365 plan doesn't include it, the alternative is an Outlook rule that
> auto-forwards these emails to an inbound-parse address (e.g. Cloudflare Email
> Routing / SendGrid Inbound) that POSTs the same `repository_dispatch` — ask
> and I'll set that up instead.

---

## How it behaves

- **Idempotent**: if the learner already holds an active certificate for the
  course, the run skips (no duplicate, no re-email).
- **Unmapped courses** (not in `ZOHO_COURSE_MAP`) are ignored quietly.
- **Name resolution**: the learner's email is looked up from the course roster
  by matching their name. If the name isn't a unique match, the run logs it and
  skips (rare — surface it and fix the roster name).
- To add another course, extend `ZOHO_COURSE_MAP` with its name → `{id, course}`.
