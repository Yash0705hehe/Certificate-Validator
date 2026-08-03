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

---

## Part C — Auto-provision new (non-Zoho) buyers *(optional)*

**The problem.** When someone *buys* the course but has never used Zoho, they
have no Zoho account yet. Zoho Learn's add-members API takes an existing user id
(Zuid), **not** an email, so a brand-new buyer can't be silently enrolled. By
default the purchase hook (`enroll_from_purchase.py`) just emails them a sign-up
link and they self-enrol.

This part makes it **hands-off**: the hook *invites* the buyer to your portal
automatically. Zoho emails them a one-click activation link; they set a password
(or sign in with Google) once, and they're in. They're invited as a **MEMBER
(learner)**, so they can take the course but **cannot share or re-invite anyone**
— and because your portal is private, a forwarded link is useless to a
non-member. (There is no way to give a private course to someone with *zero*
action on their part: accessing a private course requires a login, and that one
login per person is exactly what prevents sharing.)

**1. Add the scope to your refresh token.** The invite API needs
`ZohoLearn.customportaluser.CREATE` *in addition to* your existing
`ZohoLearn.course.ALL`. Regenerate the refresh token (Part A, step 2) with both
scopes, space-separated:
```
ZohoLearn.course.ALL ZohoLearn.customportaluser.CREATE
```
Update the `ZOHO_REFRESH_TOKEN` secret with the new value.

**2. Find your custom-portal id.** In Zoho Learn open your external/custom
portal's user-management screen; the id appears in the invite/resend URLs
(`.../portal/aa-impact/customportal/<THIS_ID>/invite/...`). If you're unsure,
Zoho support can tell you. Add these **GitHub repository secrets**:

   | Secret | Value |
   | --- | --- |
   | `ZOHO_CUSTOM_PORTAL_ID` | your custom-portal id |
   | `ZOHO_INVITE_URL` | *(optional)* override, only if your DC/portal path differs from the default |

**3. Complete the enrolment on acceptance.** Inviting creates the user; to drop
them straight into the course when they accept, add a **group- or
designation-based auto-enrol rule** in the course's *Add Members* settings so
new portal users in that group are enrolled automatically. (Without the rule,
they're in the portal but you'd enrol them into the course manually.)

**4. How it behaves.** The invite is **best-effort and never blocks a buyer**:
the purchase-hook status shows `zoho=invited` / `already_invited` on success, or
`invite_unconfigured` (feature off) / `invite_error: …` otherwise — and in every
non-success case the buyer still gets the course-access email as before. To
test, run the **Wix enrolment** workflow (or `enroll_from_purchase.py`) for a
throwaway email and check the `zoho=…` note in the log; leave
`ZOHO_CUSTOM_PORTAL_ID` unset to keep the plain email-link behaviour.
