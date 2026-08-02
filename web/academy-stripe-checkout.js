// AA Impact Academy — Stripe checkout integration
// ---------------------------------------------------------------------------
// Drop-in script for the standalone Academy app. It intercepts the two real
// purchase CTAs ("Enrol as an Individual" / "Buy for a Team") and sends the
// buyer to Stripe's hosted checkout (which collects name, email, card, coupon,
// and — for teams — seat quantity). The mockup card form is never used.
//
// The `create-checkout` Supabase function sets the price server-side, so the
// browser can't tamper with the amount. On success Stripe fires `stripe-webhook`,
// which records the buyer and emails their course link.
//
// To embed: this script is injected before </body> of the standalone HTML.
// Change COURSE if you sell more than the GHG course.
(function () {
  "use strict";
  var FN_BASE = "https://ukhzxqxugzqcfqcwnmvu.supabase.co/functions/v1";
  var COURSE = "GHG"; // only the GHG course is on sale today

  function ctaMode(text) {
    var t = (text || "").toLowerCase().replace(/\s+/g, " ").trim();
    if (t.indexOf("enrol as an individual") === 0) return "individual";
    if (t.indexOf("buy for a team") === 0) return "team";
    return null;
  }
  function findCta(el) {
    for (var i = 0; i < 4 && el && el.nodeType === 1; i++, el = el.parentElement) {
      if (el.tagName === "A" || el.tagName === "BUTTON" || el.getAttribute("role") === "button") {
        var mode = ctaMode(el.textContent);
        if (mode) return mode;
      }
    }
    return null;
  }
  var busy = false;
  function startCheckout(mode) {
    if (busy) return;
    busy = true;
    fetch(FN_BASE + "/create-checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course: COURSE, mode: mode }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.url) {
          window.location.href = data.url;
        } else {
          busy = false;
          alert("Checkout is temporarily unavailable. Please try again shortly.");
          console.error("create-checkout:", data);
        }
      })
      .catch(function (e) {
        busy = false;
        alert("Checkout could not start. Please try again shortly.");
        console.error(e);
      });
  }
  // Capture phase so we intercept before the app's own click handler.
  document.addEventListener(
    "click",
    function (ev) {
      var mode = findCta(ev.target);
      if (!mode) return;
      ev.preventDefault();
      ev.stopPropagation();
      startCheckout(mode);
    },
    true,
  );
})();
