"""Unit tests for the portal-invite path (auto-provisioning brand-new buyers).

These lock the request the invite API is given (URL, method, auth, body) and the
best-effort status contract the purchase hook relies on, without touching the
network — ``urllib.request.urlopen`` is patched in the module namespace.
"""

import io
import json
import urllib.error
from unittest import mock

from certissuer.zoho import CourseTarget, ZohoClient, ZohoConfig


def _cfg(custom_portal_id=None):
    return ZohoConfig(
        accounts_domain="accounts.zoho.in",
        api_domain="learn.zoho.in",
        client_id="cid",
        client_secret="secret",
        refresh_token="rtok",
        portal="aa-impact",
        course_map={"ghg accounting course": CourseTarget("111", "GHG")},
        custom_portal_id=custom_portal_id,
    )


class _Resp(io.BytesIO):
    """Minimal urlopen() context-manager stand-in."""

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        self.close()
        return False


def test_invite_unconfigured_makes_no_request():
    client = ZohoClient(_cfg(custom_portal_id=None))
    client._token = "tok"  # skip the token refresh
    with mock.patch("certissuer.zoho.urllib.request.urlopen") as urlopen:
        assert client.invite_portal_user("buyer@example.com", "Buyer") == "invite_unconfigured"
        urlopen.assert_not_called()


def test_invite_posts_expected_request():
    client = ZohoClient(_cfg(custom_portal_id="cp123"))
    client._token = "tok"
    captured = {}

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["auth"] = req.get_header("Authorization")
        captured["body"] = json.loads(req.data.decode())
        return _Resp(b'{"STATUS":"OK"}')

    with mock.patch("certissuer.zoho.urllib.request.urlopen", side_effect=fake_urlopen):
        assert client.invite_portal_user("buyer@example.com", role="MEMBER") == "invited"

    assert captured["url"] == (
        "https://learn.zoho.in/learn/api/v1/portal/aa-impact/customportal/cp123/invite"
    )
    assert captured["method"] == "POST"
    assert captured["auth"] == "Zoho-oauthtoken tok"
    assert captured["body"] == {"users": [{"emailId": "buyer@example.com", "role": "MEMBER"}]}


def test_invite_env_url_override(monkeypatch):
    monkeypatch.setenv("ZOHO_INVITE_URL", "https://example.test/invite")
    client = ZohoClient(_cfg(custom_portal_id="cp123"))
    client._token = "tok"
    seen = {}

    def fake_urlopen(req, timeout=0):
        seen["url"] = req.full_url
        return _Resp(b"{}")

    with mock.patch("certissuer.zoho.urllib.request.urlopen", side_effect=fake_urlopen):
        assert client.invite_portal_user("buyer@example.com") == "invited"
    assert seen["url"] == "https://example.test/invite"


def test_invite_duplicate_is_already_invited():
    client = ZohoClient(_cfg(custom_portal_id="cp123"))
    client._token = "tok"
    err = urllib.error.HTTPError(
        "u", 409, "Conflict", {}, io.BytesIO(b'{"message":"user already exists"}')
    )
    with mock.patch("certissuer.zoho.urllib.request.urlopen", side_effect=err):
        assert client.invite_portal_user("buyer@example.com") == "already_invited"


def test_invite_other_http_error_is_reported_not_raised():
    client = ZohoClient(_cfg(custom_portal_id="cp123"))
    client._token = "tok"
    err = urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b"bad scope"))
    with mock.patch("certissuer.zoho.urllib.request.urlopen", side_effect=err):
        status = client.invite_portal_user("buyer@example.com")
    assert status.startswith("invite_error: 401")


def test_invite_blank_email_is_a_soft_error():
    client = ZohoClient(_cfg(custom_portal_id="cp123"))
    client._token = "tok"
    with mock.patch("certissuer.zoho.urllib.request.urlopen") as urlopen:
        assert client.invite_portal_user("  ") == "invite_error: no email"
        urlopen.assert_not_called()
