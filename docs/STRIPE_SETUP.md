# Stripe checkout — end-to-end setup

This wires **real payments** into the AA Impact Academy app and connects them to
the enrolment → course → certificate pipeline. The heavy lifting (two Supabase
Edge Functions + the app's Pay button) is already built and deployed; this doc is
the setup **you** do in Stripe/Supabase/hosting.

```
Academy app: "Enrol as an Individual" / "Buy for a Team"
   → create-checkout function  (sets price server-side, returns Stripe URL)
   → Stripe hosted checkout     ← real card payment, coupon, team seats, name+email
   → stripe-webhook function    (SOURCE OF TRUTH a payment happened):
        • records buyer in Supabase enrolments
        • emails their Zoho course-access link (Brevo)
   → learner finishes course → Zoho completion email → certificate issued + emailed
   → anyone can verify it in the app's "Validate Certificate" (already live)
```

**Already done (by Claude):**
- `create-checkout` function — deployed: `https://ukhzxqxugzqcfqcwnmvu.supabase.co/functions/v1/create-checkout`
- `stripe-webhook` function — deployed: `https://ukhzxqxugzqcfqcwnmvu.supabase.co/functions/v1/stripe-webhook`
- `public.enrolments` table (buyer records)
- The app's Pay buttons wired to Stripe (`AA_Impact_Academy_Stripe.html`, tested)

---

## Part A — Stripe: account, product, keys

1. Create/sign in to a **Stripe** account (business: AA Impact Inc.). Start in
   **Test mode** (toggle top-right) until it all works, then switch to Live.
2. **Products → + Add product**: name *GHG Accounting Course*, set a **one-time**
   price in **CAD**. Save, then copy the **Price ID** (looks like `price_...`).
3. **Developers → API keys**: copy the **Secret key** (`sk_test_...`, later
   `sk_live_...`). You do **not** need the publishable key.

## Part B — Stripe: webhook endpoint

1. **Developers → Webhooks → + Add endpoint**.
2. Endpoint URL:
   `https://ukhzxqxugzqcfqcwnmvu.supabase.co/functions/v1/stripe-webhook`
3. **Events to send**: select **`checkout.session.completed`**.
4. Add the endpoint, then copy its **Signing secret** (`whsec_...`).

## Part C — Supabase: function secrets

Supabase dashboard → **Project Settings → Edge Functions → Manage secrets** (or
**Edge Functions → Secrets**). Add:

| Secret | Value |
| ------ | ----- |
| `STRIPE_SECRET_KEY` | `sk_test_...` (then `sk_live_...` when live) |
| `STRIPE_WEBHOOK_SECRET` | `whsec_...` from Part B |
| `STRIPE_PRICES` | `{"GHG": "price_..."}` — the Price ID from Part A |
| `APP_BASE_URL` | where the app is hosted, e.g. `https://academy.aaimpactinc.com` |
| `BREVO_API_KEY` | your Brevo key (same one the certificate emails use) |
| `BREVO_FROM` | `AA Impact Academy <certificate@aaimpactinc.com>` |
| `COURSE_ACCESS_URLS` | `{"GHG": "https://learn.zoho.in/portal/aa-impact/course/58084000000002174"}` |

`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are provided automatically — don't add them.

Get the **Zoho course link** (for `COURSE_ACCESS_URLS`) from your course in Zoho
Learn (open the course → copy its URL / Share link). Set the course to allow
learners to **sign up / self-enrol** so a brand-new buyer can create a login
with the email they paid with.

## Part D — Host the app + point your subdomain

1. Host **`AA_Impact_Academy_Stripe.html`** (the wired file Claude sent) as
   `index.html` on any free static host — **GitHub Pages**, Cloudflare Pages,
   Netlify, or Vercel. (No build step; it's a single self-contained file.)
2. In your **Wix** domain settings, add a **CNAME** record so
   `academy.aaimpactinc.com` points at the host (each host shows the exact
   target). This is a CNAME, which Wix supports.
3. Make sure `APP_BASE_URL` (Part C) matches the final URL.

---

## Test it (Stripe Test mode)

1. Open the hosted app, click **Enrol as an Individual**.
2. On Stripe's page use the test card **4242 4242 4242 4242**, any future expiry,
   any CVC, and a name + email.
3. After paying you're redirected back to the app. Within a few seconds:
   - a row appears in Supabase **`enrolments`** (name, email, amount), and
   - the buyer gets the **welcome email** with the course link.
4. In Stripe → **Developers → Webhooks**, confirm the `checkout.session.completed`
   delivery shows **200**.
5. When it all works, switch Stripe to **Live**, swap `STRIPE_SECRET_KEY` to
   `sk_live_...`, and add a **live** webhook endpoint (its secret replaces
   `STRIPE_WEBHOOK_SECRET`).

## Notes

- **Price is server-side.** The amount comes from `STRIPE_PRICES`, so the browser
  can never change what's charged. Coupons are entered on Stripe's page; team
  buyers choose their seat count there too.
- **The webhook is the source of truth.** Enrolment only happens when Stripe
  confirms payment server-side — hitting the success URL can't fake it.
- **Idempotent.** Stripe retries and repeat purchases for the same
  (email, course) enrol + email once.
- **More courses later:** add them to `STRIPE_PRICES` and to `COURSE` handling in
  `web/academy-stripe-checkout.js`.
- **Selling only GHG today** is assumed; Nature/Social are waitlist in the design.
