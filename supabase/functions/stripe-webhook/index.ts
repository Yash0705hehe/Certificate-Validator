// Setup type definitions for built-in Supabase Runtime APIs
import "jsr:@supabase/functions-js/edge-runtime.d.ts";
// ============================================================================
// AA Impact Academy — Stripe payment webhook
// ============================================================================
// Stripe calls this after a successful payment. It is the SOURCE OF TRUTH that
// a payment happened (never trust the browser redirect). On
// `checkout.session.completed` it:
//   1. records the buyer in public.enrolments (idempotent per email+course),
//   2. emails them their Zoho Learn course-access link (Brevo).
// Course completion → certificate is handled by the existing pipeline.
//
// verify_jwt MUST be false: Stripe authenticates with its own signature header,
// not a Supabase JWT.
//
// Env (Supabase function secrets):
//   STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
//   BREVO_API_KEY, BREVO_FROM ("Name <email>")
//   COURSE_ACCESS_URLS  JSON { "GHG": "https://learn.zoho.in/.../course/<id>" }
//   SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY  (auto-injected by the platform)
// ============================================================================

import Stripe from "https://esm.sh/stripe@14.25.0?target=deno";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const stripe = new Stripe(Deno.env.get("STRIPE_SECRET_KEY") ?? "", {
  apiVersion: "2024-06-20",
  httpClient: Stripe.createFetchHttpClient(),
});
const cryptoProvider = Stripe.createSubtleCryptoProvider();

const supabase = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
);

const COURSE_LABELS: Record<string, string> = {
  GHG: "GHG Accounting Course",
  Nature: "Nature Course",
  GHG_Nature_Bundle: "GHG + Nature Bundle",
};

function courseAccessUrl(course: string): string {
  try {
    return String(JSON.parse(Deno.env.get("COURSE_ACCESS_URLS") ?? "{}")[course] ?? "");
  } catch {
    return "";
  }
}

function parseSender(raw: string): { name: string; email: string } {
  const m = raw.match(/^\s*(.*?)\s*<\s*([^>]+)\s*>\s*$/);
  if (m) return { name: m[1] || "AA Impact Academy", email: m[2].trim() };
  return { name: "AA Impact Academy", email: raw.trim() };
}

async function sendEnrolmentEmail(to: string, name: string, course: string) {
  const apiKey = Deno.env.get("BREVO_API_KEY");
  if (!apiKey) return { sent: false, reason: "no BREVO_API_KEY" };
  const url = courseAccessUrl(course);
  const label = COURSE_LABELS[course] ?? course;
  const sender = parseSender(Deno.env.get("BREVO_FROM") ?? "AA Impact Academy <certificate@aaimpactinc.com>");
  const button = url
    ? `<a href="${url}" style="display:inline-block;background:#17242e;color:#fff;text-decoration:none;padding:12px 22px;border-radius:6px;font-weight:bold">Go to the course</a>`
    : "";
  const html = `<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;color:#17242e;line-height:1.6">
  <p>Dear ${name},</p>
  <p>Thank you for enrolling in the <strong>${label}</strong> with AA Impact. Your payment has been received.</p>
  <p>To set up your access, use the button below to open the course and sign up / request enrolment using <em>this</em> email address — the same one you paid with, so your completion is recorded against you.</p>
  <p style="margin:22px 0">${button}</p>
  <p>Our team reviews new enrolments, so you'll receive full access to the course <strong>within 3 working days</strong>. We'll confirm once your access is live.</p>
  <p>When you complete the course, your verified AA Impact certificate is issued and emailed to you automatically.</p>
  <p style="color:#6b7280;font-size:13px">AA Impact Inc. &middot; www.aaimpactinc.com</p>
</div>`;
  const res = await fetch("https://api.brevo.com/v3/smtp/email", {
    method: "POST",
    headers: { "api-key": apiKey, "Content-Type": "application/json", accept: "application/json" },
    body: JSON.stringify({
      sender,
      to: [{ email: to }],
      subject: `Your ${label} enrolment — access within 3 working days`,
      htmlContent: html,
    }),
  });
  return { sent: res.ok, reason: res.ok ? "" : `brevo ${res.status}: ${await res.text()}` };
}

async function recordAndEmail(session: Stripe.Checkout.Session) {
  const email = (session.customer_details?.email ?? "").trim();
  const name = (session.customer_details?.name ?? "").trim() || email;
  const course = String(session.metadata?.course ?? "").trim();
  if (!email || !course) {
    console.error("Missing email/course on session", session.id);
    return;
  }

  // Idempotency: one enrolment per (lower(email), course).
  const { data: existing } = await supabase
    .from("enrolments")
    .select("id, enrol_email_sent")
    .ilike("buyer_email", email)
    .eq("course", course)
    .limit(1);

  let rowId = existing?.[0]?.id as string | undefined;
  const alreadyEmailed = existing?.[0]?.enrol_email_sent === true;

  if (!rowId) {
    const { data: ins, error } = await supabase
      .from("enrolments")
      .insert({
        buyer_name: name,
        buyer_email: email,
        course,
        source: "stripe",
        wix_order_id: session.id, // reuse column as the Stripe session id
        amount: (session.amount_total ?? 0) / 100,
        currency: (session.currency ?? "").toUpperCase(),
        raw: { stripe_session_id: session.id, quantity: session.metadata?.quantity ?? "1" },
      })
      .select("id")
      .single();
    if (error) {
      console.error("enrolment insert failed", error.message);
      return;
    }
    rowId = ins.id;
  }

  if (alreadyEmailed) return; // idempotent: don't re-email on Stripe retries

  const emailed = await sendEnrolmentEmail(email, name, course);
  await supabase
    .from("enrolments")
    .update({ enrol_email_sent: emailed.sent, processed_at: new Date().toISOString() })
    .eq("id", rowId);
  if (!emailed.sent) console.error("welcome email failed:", emailed.reason);
}

Deno.serve(async (req) => {
  const sig = req.headers.get("stripe-signature");
  const secret = Deno.env.get("STRIPE_WEBHOOK_SECRET");
  const rawBody = await req.text();
  if (!sig || !secret) return new Response("Missing signature/secret", { status: 400 });

  let event: Stripe.Event;
  try {
    event = await stripe.webhooks.constructEventAsync(rawBody, sig, secret, undefined, cryptoProvider);
  } catch (err) {
    return new Response(`Webhook signature verification failed: ${err}`, { status: 400 });
  }

  try {
    if (event.type === "checkout.session.completed") {
      await recordAndEmail(event.data.object as Stripe.Checkout.Session);
    }
  } catch (err) {
    // Log but still 200 so Stripe doesn't hammer retries on a transient issue;
    // the enrolment is idempotent and can be replayed from the Stripe dashboard.
    console.error("handler error", String(err));
  }
  return new Response(JSON.stringify({ received: true }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});
