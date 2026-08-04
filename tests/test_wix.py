"""Unit tests for the Wix Forms submission capture (email-capture poller).

These lock the field extraction (email + name out of a real "Payment" form
submission shape), the query request the poller sends, and the buyer-mapping
rules — all without network (``urllib.request.urlopen`` is patched).
"""

import io
import json
from unittest import mock

from certissuer.wix import (
    DEFAULT_FORM_COURSE_MAP,
    WixClient,
    WixConfig,
    _extract_email,
    _extract_name,
)

GHG_FORM = "a2b557bc-9d1e-4125-bf90-9224c5c07978"


def _cfg():
    return WixConfig(
        api_key="key-123",
        site_id="site-abc",
        form_course_map=dict(DEFAULT_FORM_COURSE_MAP),
        lookback_days=0,
    )


# Mirrors the real "Payment" form field targets (email_076a / first_name_e962 /
# last_name_5267), plus non-string fields that must be ignored.
PAYMENT_FIELDS = {
    "first_name_e962": "Ravi",
    "last_name_5267": "Kumar",
    "email_076a": "ravi@example.com",
    "license": ["Individual"],
    "product": {"id": "11451f2e"},
}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_a):
        self.close()
        return False


def test_extract_email_and_name_from_payment_fields():
    assert _extract_email(PAYMENT_FIELDS) == "ravi@example.com"
    assert _extract_name(PAYMENT_FIELDS) == "Ravi Kumar"


def test_extract_email_falls_back_to_regex_when_key_unusual():
    assert _extract_email({"contact_9f": "someone@aa.com"}) == "someone@aa.com"
    assert _extract_email({"note": "no address here"}) is None


def test_query_sends_confirmed_paid_form_filter():
    client = WixClient(_cfg())
    captured = {}

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["site"] = req.get_header("Wix-site-id")
        captured["body"] = json.loads(req.data.decode())
        return _Resp(b'{"submissions": [], "metadata": {"hasNext": false}}')

    with mock.patch("certissuer.wix.urllib.request.urlopen", side_effect=fake_urlopen):
        client.query_confirmed_submissions()

    assert captured["url"].endswith("/forms/v4/submissions/namespace/query")
    assert captured["auth"] == "key-123"
    assert captured["site"] == "site-abc"
    filt = captured["body"]["query"]["filter"]
    assert filt["namespace"] == "wix.form_app.form"
    assert filt["status"] == {"$eq": "CONFIRMED"}
    assert filt["formId"] == {"$in": [GHG_FORM]}


def test_buyers_maps_confirmed_submission_to_course():
    client = WixClient(_cfg())
    subs = [
        {"id": "sub1", "formId": GHG_FORM, "status": "CONFIRMED", "submissions": PAYMENT_FIELDS},
        # unpaid → skipped
        {"id": "sub2", "formId": GHG_FORM, "status": "PAYMENT_WAITING", "submissions": PAYMENT_FIELDS},
        # unmapped form → skipped
        {"id": "sub3", "formId": "other-form", "status": "CONFIRMED", "submissions": PAYMENT_FIELDS},
    ]
    buyers = client.buyers(subs)
    assert len(buyers) == 1
    b = buyers[0]
    assert (b.email, b.name, b.course, b.submission_id) == (
        "ravi@example.com",
        "Ravi Kumar",
        "GHG",
        "sub1",
    )


def test_buyers_skips_submission_without_email():
    client = WixClient(_cfg())
    subs = [
        {"id": "s", "formId": GHG_FORM, "status": "CONFIRMED", "submissions": {"first_name_e962": "No Email"}},
    ]
    assert client.buyers(subs) == []


def test_from_env_requires_api_key(monkeypatch):
    monkeypatch.delenv("WIX_API_KEY", raising=False)
    try:
        WixConfig.from_env()
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "WIX_API_KEY" in str(e)


def test_from_env_defaults_form_map(monkeypatch):
    monkeypatch.setenv("WIX_API_KEY", "k")
    monkeypatch.delenv("WIX_FORM_COURSE_MAP", raising=False)
    monkeypatch.delenv("WIX_SITE_ID", raising=False)
    cfg = WixConfig.from_env()
    assert cfg.form_course_map == DEFAULT_FORM_COURSE_MAP
    assert cfg.site_id == "bc6a0452-5643-4224-a190-e0c157754f82"
