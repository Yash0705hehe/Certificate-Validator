# Paid enrolment on your Wix site (aaimpactinc.com)

This connects the certificate system to your **paid** Wix site so that when
someone buys the course, a real payment is taken, you capture their **name and
email**, they're given course access, and — once they finish — their
certificate is issued and emailed automatically.

Your paid site is **AA Impact Inc.** (`www.aaimpactinc.com`) — Premium plan,
custom domain, **Velo enabled**, with **Wix Forms & Payments** and **Wix
Pricing Plans** available. That's everything needed; the free "Certificate
Validator" prototype could not take payments, this site can.

```
Buyer pays on aaimpactinc.com  (real gateway, name + email captured)
   → Velo backend event on successful payment
       → GitHub repository_dispatch  (type: wix_enrolment)
           → "Wix enrolment" workflow:
               • records the buyer in Supabase (enrolments table)
               • emails them the Zoho Learn course-access link
               • best-effort auto-enrol if already a Zoho user
   → buyer takes the course → Zoho completion email
       → (existing) Power Automate → certificate issued + emailed
```

You can do this in two phases. **Phase 1 alone already answers "a real gateway
and how do I get their name + email."** Phase 2 adds the hands-off automation.

---

## Email capture on THIS site (Wix Forms & Payments) — the poller

> **Important:** aaimpactinc.com takes payment through a **Wix Forms & Payments**
> form (the "Payment" form), **not** Pricing Plans or Wix Stores. The Velo
> `events.js` in Phase 2 below listens for a *Pricing Plan* purchase event that
> **never fires on this site** — that's why the buyer's email was never captured.
> The mechanism that actually works here is the **poller** described in this
> section. (Keep Phase 2 only as a reference for if you ever switch to Pricing
> Plans.)

Because a Forms & Payments checkout gives us no purchase event to push the email,
we **pull** it: a scheduled GitHub Action lists the paid form submissions (Wix
marks a submission `CONFIRMED` once payment succeeds) and runs each buyer through
the same enrolment pipeline.

```
Buyer pays on the "Payment" form  → Wix stores the submission (CONFIRMED)
   → .github/workflows/wix-submission-poll.yml (hourly)
       → poll_wix_submissions.py reads name + email + course
           → process_purchase(): records in Supabase (idempotent),
             best-effort Zoho enrol / invite, emails the course link
```

**Set it up (one API key, no code to paste into Wix):**

1. **Create a Wix API key.** https://manage.wix.com/account/api-keys →
   **Generate API key** → give it the **Wix Forms → Read Submissions**
   permission → copy the key.
2. **Add GitHub repository secrets** (Settings → Secrets and variables → Actions):

   | Secret | Value |
   | --- | --- |
   | `WIX_API_KEY` | the key from step 1 |
   | `WIX_SITE_ID` | `bc6a0452-5643-4224-a190-e0c157754f82` |
   | `WIX_FORM_COURSE_MAP` | `{"a2b557bc-9d1e-4125-bf90-9224c5c07978": "GHG"}` |
   | `WIX_POLL_LOOKBACK_DAYS` | *(optional)* e.g. `30` to only scan recent submissions |

   The `SUPABASE_*`, `BREVO_*`, `COURSE_ACCESS_URLS`, and `ZOHO_*`
   (incl. optional `ZOHO_CUSTOM_PORTAL_ID`) secrets are reused from the other
   workflows.
3. **Test it:** repo → **Actions → Wix submission poll → Run workflow** with
   **Dry run = true**. The log lists the paid buyers it *would* enrol (their
   name + email resolved from the form). Untick Dry run to actually record +
   enrol + email them. After that it runs **hourly** on its own.

To sell another course later, add its paid form and extend `WIX_FORM_COURSE_MAP`
with `"<that form id>": "Nature"` (find the form id via the same Wix Forms list).

---

## Phase 1 — Take real payments and capture buyers (no code)

Pick **one** checkout style on aaimpactinc.com:

### Option A — Pricing Plan (recommended for selling course access)
1. Wix dashboard → **Pricing Plans** → **+ New Plan**.
2. Name it e.g. *GHG Accounting Course*, set a **one-time** price in your
   currency, Save.
3. Add the plan to a page (a **Pricing Plans** / list section, or a Buy button).
4. Dashboard → **Settings → Accept Payments** → connect a provider (Wix
   Payments, Stripe, PayPal, etc.). This is the real gateway.

### Option B — Paid Form (simplest for capturing name + email directly)
1. Add a **Wix Form** with **Name** and **Email** fields.
2. In the form's settings turn on **Payment** and set the price.
3. Connect a payment provider as above.

**Where the buyer details land (both options):** Wix dashboard →
**Contacts** and **Pricing Plans → Orders** (Option A) or **Forms →
Submissions** (Option B). Every buyer's name, email, and payment is recorded
there automatically — that's your list.

> Do Phase 1 first and confirm a test purchase shows up under Contacts/Orders.
> Then add Phase 2 to make it hands-off.

---

## Phase 2 — Velo → GitHub (reference only; not used on this site)

> **This site uses the poller above, not this.** The Velo handler below is the
> *Pricing Plans* purchase event and does **not** fire on a Wix Forms & Payments
> checkout. Keep this section only if you migrate the course to Pricing Plans.

### Auto-enrol + auto-certificate (Velo → GitHub)

### 2.1 One-time secrets

**In GitHub** (repo → Settings → Secrets and variables → Actions → New
repository secret) — most already exist from the certificate setup; add the new
one:

| Secret | Value |
| ------ | ----- |
| `COURSE_ACCESS_URLS` | JSON map of course → Zoho course link, e.g. `{"GHG": "https://learn.zoho.in/portal/aa-impact/course/scope-3-quiz"}` |

Already present from before (reused as-is): `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, `BREVO_API_KEY`, `BREVO_FROM`, and the `ZOHO_*`
secrets.

Get the **course link** from Zoho Learn: open the course → **Share** (or copy
the course URL from the address bar). In the course's enrolment settings, allow
learners to **sign up / self-enrol** so a brand-new buyer can create their
login with the same email they paid with.

**In Wix** (dashboard → **Settings → Secrets Manager**):

| Secret name | Value |
| ----------- | ----- |
| `GITHUB_DISPATCH_TOKEN` | A GitHub **fine-grained personal access token** scoped to this repo with **Contents: Read and write** (this permission is what lets it fire `repository_dispatch`). |

### 2.2 Velo backend event

Turn on **Dev Mode** (top bar → **Dev Mode / Velo**), then:

1. In the Velo sidebar open **Backend** → the file **`events.js`** (create it if
   it doesn't exist).
2. Paste the handler below. It fires on a successful Pricing Plan purchase,
   looks up the buyer's name + email, and fires the GitHub workflow.

```javascript
// backend/events.js
import { members } from 'wix-members-backend';
import { getSecret } from 'wix-secrets-backend';
import { fetch } from 'wix-fetch';

// Map a purchased plan name -> our course key (GHG / Nature / GHG_Nature_Bundle).
const PLAN_TO_COURSE = {
  'GHG Accounting Course': 'GHG',
  // 'Nature Course': 'Nature',
  // 'GHG + Nature Bundle': 'GHG_Nature_Bundle',
};

const GITHUB_OWNER = 'yash0705hehe';
const GITHUB_REPO = 'certificate-validator';

export async function wixPricingPlans_onOrderPurchased(event) {
  try {
    const order = event.order || event;
    const planName = order.planName || (order.plan && order.plan.name) || '';
    const course = PLAN_TO_COURSE[planName];
    if (!course) return; // not a course plan we care about

    // Resolve the buyer's name + email from their member record.
    const memberId = order.buyer && order.buyer.memberId;
    let name = '', email = '';
    if (memberId) {
      const m = await members.getMember(memberId, { fieldsets: ['FULL'] });
      email = (m.loginEmail || (m.contactDetails && m.contactDetails.emails && m.contactDetails.emails[0]) || '');
      const c = m.contactDetails || {};
      name = [c.firstName, c.lastName].filter(Boolean).join(' ').trim() || email;
    }
    if (!email) return;

    const token = await getSecret('GITHUB_DISPATCH_TOKEN');
    await fetch(`https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/dispatches`, {
      method: 'post',
      headers: {
        'Accept': 'application/vnd.github+json',
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        event_type: 'wix_enrolment',
        client_payload: {
          name,
          email,
          course,
          order_id: order._id || order.id || '',
          amount: (order.priceDetails && order.priceDetails.total) || '',
          currency: (order.priceDetails && order.priceDetails.currency) || '',
        },
      }),
    });
  } catch (e) {
    console.error('wix_enrolment dispatch failed', e);
  }
}
```

> **Using a paid Form instead of a Pricing Plan?** Use the Wix **Automations**
> or Forms submit event to call the same `fetch(...)` block — the `name` and
> `email` come straight off the submitted form fields, so you can skip the
> `members.getMember` lookup.

3. **Publish** the site.

### 2.3 Test it

- **From GitHub (no payment needed):** repo → **Actions → Wix enrolment → Run
  workflow**, enter a name + email + `GHG`, tick **Dry run** first. A dry run
  reports what would happen; an un-ticked run records the buyer in Supabase and
  emails the course link.
- **End to end:** make a real (or test-mode) purchase on aaimpactinc.com and
  confirm a **Wix enrolment** run appears in Actions within a minute, the buyer
  shows up in the Supabase `enrolments` table, and the welcome email arrives.

---

## What each piece does

| Piece | Role |
| ----- | ---- |
| Wix Pricing Plan / paid Form | Real payment gateway + captures buyer name/email |
| `backend/events.js` (Velo) | Fires GitHub `repository_dispatch` on successful payment |
| `.github/workflows/wix-enrolment.yml` | Runs the enrolment on each purchase |
| `enroll_from_purchase.py` | Records the buyer, emails the course link, best-effort Zoho enrol |
| `public.enrolments` (Supabase) | Your buyer list — one row per (email, course) |
| Existing Zoho→Power Automate→certificate flow | Issues + emails the certificate on completion |

## Notes & limits

- **Email capture is a pull, not a push.** This site's Forms & Payments checkout
  gives no purchase event, so `wix-submission-poll.yml` polls the Wix Forms API
  hourly for `CONFIRMED` (paid) submissions. A buyer therefore gets enrolled
  within ~1 hour of paying, not instantly — fine against the "access within 3
  working days" promise. Lower the cron in the workflow if you want it faster.
- **Zoho auto-enrol is best-effort.** Zoho Learn's add-member API takes an
  existing Zoho user id, not an email, so a brand-new buyer can't be added by
  API. Anyone who is already a Zoho user is detected and reported as already
  enrolled. For brand-new buyers you have two options: (a) leave it as-is and
  the welcome email's **course-access link** lets them self-enrol with their
  paid email; or (b) turn on **auto-provisioning** so the hook *invites* them to
  the portal automatically as a learner (they can't share the course) — see
  **docs/ZOHO_SETUP.md → Part C**. Either way the welcome email is still sent as
  a fallback.
- **Idempotent.** A retried webhook or a repeat run for the same
  (email, course) is a no-op — the buyer is enrolled and emailed once.
- **Certificate step is unchanged.** Completion still flows through the existing
  Zoho completion email → Power Automate → certificate pipeline.
