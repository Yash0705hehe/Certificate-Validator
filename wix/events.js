// backend/events.js — paste this into the Backend section of your Wix site
// (Dev Mode → Backend → events.js; create the file if it doesn't exist).
//
// Fires the enrolment pipeline the instant a paid "Payment" form submission is
// CONFIRMED (i.e. the buyer has paid). Reads the submission NATIVELY inside Wix
// — no API key, so it can't hit the submissions-API 403 the poller ran into.
//
// It POSTs a GitHub repository_dispatch (event_type: wix_enrolment), which the
// existing "Wix enrolment" workflow handles: records the buyer in Supabase,
// invites/auto-enrols them into the Zoho hub course, and emails their link.
//
// One-time setup (see docs/WIX_ENROLMENT_SETUP.md):
//   1. Wix Dashboard → Settings → Secrets Manager → add GITHUB_DISPATCH_TOKEN
//      = a GitHub fine-grained PAT for this repo with Contents: Read and write.
//   2. Paste this file, then Publish the site.

import { getSecret } from 'wix-secrets-backend';
import { fetch } from 'wix-fetch';

const GITHUB_OWNER = 'Yash0705hehe';
const GITHUB_REPO = 'Certificate-Validator';

// Each PAID form id -> our course key. Add a line here when you sell another
// course through a new paid form (find the form id the same way we found this).
const FORM_TO_COURSE = {
  'a2b557bc-9d1e-4125-bf90-9224c5c07978': 'GHG', // the "Payment" form
};

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function extractEmail(fields) {
  // Prefer a field keyed like "email" (Wix targets look like email_076a)…
  for (const key of Object.keys(fields)) {
    const v = fields[key];
    if (typeof v === 'string' && key.toLowerCase().startsWith('email') && EMAIL_RE.test(v.trim())) {
      return v.trim();
    }
  }
  // …otherwise any value that looks like an email address.
  for (const key of Object.keys(fields)) {
    const v = fields[key];
    if (typeof v === 'string' && EMAIL_RE.test(v.trim())) return v.trim();
  }
  return '';
}

function extractName(fields) {
  let first = '', last = '', full = '';
  for (const key of Object.keys(fields)) {
    const v = fields[key];
    if (typeof v !== 'string') continue;
    const k = key.toLowerCase();
    if (k.startsWith('first_name')) first = v.trim();
    else if (k.startsWith('last_name')) last = v.trim();
    else if (k === 'name' || k.startsWith('full_name')) full = v.trim();
  }
  return (`${first} ${last}`.trim() || full).trim();
}

async function dispatchIfPaid(event) {
  try {
    const entity = event && event.entity;
    if (!entity) return;

    const course = FORM_TO_COURSE[entity.formId];
    if (!course) return;                       // not a paid course form we track
    if (entity.status !== 'CONFIRMED') return; // only once payment has gone through

    const fields = entity.submissions || {};
    const email = extractEmail(fields);
    if (!email) {
      console.error('wix_enrolment: no email found in submission', entity._id);
      return;
    }
    const name = extractName(fields) || email.split('@')[0];

    const token = await getSecret('GITHUB_DISPATCH_TOKEN');
    const res = await fetch(
      `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/dispatches`,
      {
        method: 'post',
        headers: {
          'Accept': 'application/vnd.github+json',
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
          'User-Agent': 'aa-impact-forms',
        },
        body: JSON.stringify({
          event_type: 'wix_enrolment',
          client_payload: { name, email, course, order_id: entity._id },
        }),
      }
    );
    // GitHub returns 204 No Content on success.
    if (!res.ok) {
      console.error('wix_enrolment dispatch failed', res.status, await res.text());
    } else {
      console.log('wix_enrolment dispatched:', email, course);
    }
  } catch (e) {
    console.error('wix_enrolment handler error', e);
  }
}

// A paid submission is created as PENDING/PAYMENT_WAITING (skipped), then updated
// to CONFIRMED once paid (dispatched). Both handlers guard on status, and the
// pipeline is idempotent on (email, course), so any overlap is a harmless no-op.
export function wixForms_onSubmissionCreated(event) {
  return dispatchIfPaid(event);
}

export function wixForms_onSubmissionUpdated(event) {
  return dispatchIfPaid(event);
}
