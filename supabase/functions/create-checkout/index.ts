// Setup type definitions for built-in Supabase Runtime APIs
import "jsr:@supabase/functions-js/edge-runtime.d.ts";
// ============================================================================
// AA Impact Academy — create Stripe Checkout Session
// ============================================================================
// Called from the Academy app's "Pay" button. Creates a Stripe Checkout
// Session for the chosen course (price is set SERVER-SIDE from STRIPE_PRICES so
// the browser can never tamper with the amount) and returns the hosted
// checkout URL to redirect to. Coupons are entered on Stripe's page
// (allow_promotion_codes). On success Stripe fires the `stripe-webhook`
// function, which records the buyer and emails their course link.
//
//   POST /create-checkout  { "course": "GHG", "quantity": 1 }
//     -> { "url": "https://checkout.stripe.com/c/pay/..." }
//
// Env (Supabase function secrets):
//   STRIPE_SECRET_KEY   sk_live_... / sk_test_...
//   STRIPE_PRICES       JSON { "GHG": "price_123", ... }  (Stripe Price IDs)
//   APP_BASE_URL        e.g. https://academy.aaimpactinc.com  (success/cancel)
//   ALLOWED_ORIGIN      optional CORS origin (defaults to "*")
// ============================================================================

import Stripe from "https://esm.sh/stripe@14.25.0?target=deno";

const stripe = new Stripe(Deno.env.get("STRIPE_SECRET_KEY") ?? "", {
  apiVersion: "2024-06-20",
  httpClient: Stripe.createFetchHttpClient(),
});

const APP_BASE_URL = (Deno.env.get("APP_BASE_URL") ?? "").replace(/\/+$/, "");

function priceMap(): Record<string, string> {
  try {
    return JSON.parse(Deno.env.get("STRIPE_PRICES") ?? "{}");
  } catch {
    return {};
  }
}

const corsHeaders = {
  "Access-Control-Allow-Origin": Deno.env.get("ALLOWED_ORIGIN") ?? "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (req.method !== "POST") return json({ error: "Method not allowed" }, 405);

  try {
    const body = await req.json().catch(() => ({}));
    const course = String(body.course ?? "").trim();
    const mode = String(body.mode ?? "individual").trim(); // "individual" | "team"
    let quantity = parseInt(String(body.quantity ?? "1"), 10);
    if (!Number.isFinite(quantity) || quantity < 1) quantity = 1;
    if (quantity > 100) quantity = 100;

    const prices = priceMap();
    const priceId = prices[course];
    if (!priceId) {
      return json(
        { error: `Unknown or unconfigured course: ${course || "(none)"}` },
        400,
      );
    }
    if (!APP_BASE_URL) return json({ error: "APP_BASE_URL not configured" }, 500);

    // Teams pick their seat count on Stripe's page; individuals get a fixed 1.
    const lineItem: Record<string, unknown> = { price: priceId, quantity };
    if (mode === "team") {
      lineItem.adjustable_quantity = { enabled: true, minimum: 1, maximum: 100 };
    }

    const session = await stripe.checkout.sessions.create({
      mode: "payment",
      line_items: [lineItem],
      allow_promotion_codes: true,
      billing_address_collection: "auto",
      // Ensure we capture the buyer's name + email for enrolment.
      customer_creation: "always",
      phone_number_collection: { enabled: false },
      metadata: { course, quantity: String(quantity) },
      success_url: `${APP_BASE_URL}/?enrolled=1&session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${APP_BASE_URL}/?checkout=cancelled`,
    });

    return json({ url: session.url });
  } catch (err) {
    return json({ error: "Could not create checkout.", detail: String(err) }, 500);
  }
});
