"""Unit tests for the hub-based auto-enrolment of brand-new buyers.

Covers the invite-to-hub request shape, hub Zuid resolution across response
shapes, and the ensure_course_access decision tree — all without network
(``urllib.request.urlopen`` is patched, or client methods are mocked directly).
"""

import io
import json
import urllib.error
from unittest import mock

from certissuer.zoho import CourseTarget, ZohoClient, ZohoConfig


def _cfg(auto_enroll=True):
    return ZohoConfig(
        accounts_domain="accounts.zoho.in",
        api_domain="learn.zoho.in",
        client_id="cid",
        client_secret="secret",
        refresh_token="rtok",
        portal="aa-impact",
        course_map={"ghg accounting course": CourseTarget("111", "GHG")},
        auto_enroll=auto_enroll,
    )


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_a):
        self.close()
        return False


# --- invite_to_hub -------------------------------------------------------

def test_invite_to_hub_posts_expected_request():
    client = ZohoClient(_cfg())
    client._token = "tok"
    captured = {}

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["auth"] = req.get_header("Authorization")
        captured["body"] = json.loads(req.data.decode())
        return _Resp(b'{"STATUS":"OK"}')

    with mock.patch("certissuer.zoho.urllib.request.urlopen", side_effect=fake_urlopen):
        assert client.invite_to_hub("buyer@example.com", "Ravi Kumar") == "invited"

    assert captured["url"] == "https://learn.zoho.in/learn/api/v1/hubs/aa-impact/invite"
    assert captured["method"] == "POST"
    assert captured["auth"] == "Zoho-oauthtoken tok"
    assert captured["body"] == {
        "userlist": [{"emailId": "buyer@example.com", "fname": "Ravi", "lname": "Kumar"}]
    }


def test_invite_to_hub_duplicate_is_already_invited():
    client = ZohoClient(_cfg())
    client._token = "tok"
    err = urllib.error.HTTPError(
        "u", 409, "Conflict", {}, io.BytesIO(b'{"message":"user already exists"}')
    )
    with mock.patch("certissuer.zoho.urllib.request.urlopen", side_effect=err):
        assert client.invite_to_hub("buyer@example.com") == "already_invited"


def test_invite_to_hub_blank_email_is_soft_error():
    client = ZohoClient(_cfg())
    client._token = "tok"
    with mock.patch("certissuer.zoho.urllib.request.urlopen") as urlopen:
        assert client.invite_to_hub("  ") == "invite_error: no email"
        urlopen.assert_not_called()


# --- hub_member_zuid -----------------------------------------------------

def test_hub_member_zuid_course_shape():
    client = ZohoClient(_cfg())
    client._token = "tok"
    body = b'{"MEMBERS":{"usersDetails":[{"emailId":"buyer@example.com","id":"zuid-1"}]}}'
    with mock.patch("certissuer.zoho.urllib.request.urlopen", return_value=_Resp(body)):
        assert client.hub_member_zuid("BUYER@example.com") == "zuid-1"


def test_hub_member_zuid_flat_shape():
    client = ZohoClient(_cfg())
    client._token = "tok"
    body = b'{"members":[{"emailId":"other@x.com","zuid":"9"},{"emailId":"buyer@example.com","zuid":"z2"}]}'
    with mock.patch("certissuer.zoho.urllib.request.urlopen", return_value=_Resp(body)):
        assert client.hub_member_zuid("buyer@example.com") == "z2"


def test_hub_member_zuid_not_found_returns_none():
    client = ZohoClient(_cfg())
    client._token = "tok"
    with mock.patch("certissuer.zoho.urllib.request.urlopen", return_value=_Resp(b'{"members":[]}')):
        assert client.hub_member_zuid("buyer@example.com") is None


def test_hub_member_zuid_swallows_errors():
    client = ZohoClient(_cfg())
    client._token = "tok"
    err = urllib.error.HTTPError("u", 403, "Forbidden", {}, io.BytesIO(b"nope"))
    with mock.patch("certissuer.zoho.urllib.request.urlopen", side_effect=err):
        assert client.hub_member_zuid("buyer@example.com") is None


# --- ensure_course_access decision tree ----------------------------------

def test_ensure_already_member():
    client = ZohoClient(_cfg())
    with mock.patch.object(client, "find_member", return_value={"id": "z"}):
        assert client.ensure_course_access("111", "buyer@example.com") == "already_member"


def test_ensure_enrolls_existing_hub_user():
    client = ZohoClient(_cfg())
    with mock.patch.object(client, "find_member", return_value=None), mock.patch.object(
        client, "hub_member_zuid", return_value="zuid-9"
    ), mock.patch.object(client, "enroll_member", return_value={}) as enroll:
        assert client.ensure_course_access("111", "buyer@example.com") == "enrolled"
        enroll.assert_called_once_with("111", ["zuid-9"], role="MEMBER")


def test_ensure_invites_brand_new_buyer():
    client = ZohoClient(_cfg())
    with mock.patch.object(client, "find_member", return_value=None), mock.patch.object(
        client, "hub_member_zuid", return_value=None
    ), mock.patch.object(client, "invite_to_hub", return_value="invited") as invite:
        assert client.ensure_course_access("111", "buyer@example.com", "Ravi") == "invited"
        invite.assert_called_once_with("buyer@example.com", "Ravi")


def test_from_env_reads_auto_enroll(monkeypatch):
    for k, v in {
        "ZOHO_CLIENT_ID": "x",
        "ZOHO_CLIENT_SECRET": "y",
        "ZOHO_REFRESH_TOKEN": "z",
        "ZOHO_PORTAL": "aa-impact",
        "ZOHO_COURSE_MAP": '{"GHG Accounting Course": {"id":"111","course":"GHG"}}',
        "ZOHO_AUTO_ENROLL": "true",
    }.items():
        monkeypatch.setenv(k, v)
    assert ZohoConfig.from_env().auto_enroll is True
    monkeypatch.setenv("ZOHO_AUTO_ENROLL", "no")
    assert ZohoConfig.from_env().auto_enroll is False
