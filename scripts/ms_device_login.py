#!/usr/bin/env python3
"""One-time device-code login to mint a Microsoft Graph refresh token for the
certificate@ mailbox.

Run this ONCE on your computer. It prints a code + URL; you sign in as
certificate@aaimpactinc.com in a browser, and it prints a refresh_token to save
as the MS_REFRESH_TOKEN GitHub secret.

    python scripts/ms_device_login.py --tenant <TENANT_ID> --client <CLIENT_ID>

Requires only the standard library. The app registration must allow public
client flows (see docs/MS_GRAPH_SETUP.md).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SCOPE = "offline_access Mail.Read"


def _post(url: str, form: dict) -> tuple[int, dict]:
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True, help="Directory (tenant) ID")
    ap.add_argument("--client", required=True, help="Application (client) ID")
    args = ap.parse_args()

    base = f"https://login.microsoftonline.com/{args.tenant}/oauth2/v2.0"

    status, dc = _post(f"{base}/devicecode", {"client_id": args.client, "scope": SCOPE})
    if "device_code" not in dc:
        print(f"Failed to start device login: {dc}", file=sys.stderr)
        return 1

    print("\n=== Sign in to authorize ===")
    print(dc.get("message") or f"Go to {dc['verification_uri']} and enter code: {dc['user_code']}")
    print("Sign in as certificate@aaimpactinc.com.\n")

    interval = int(dc.get("interval", 5))
    while True:
        time.sleep(interval)
        status, tok = _post(
            f"{base}/token",
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": args.client,
                "device_code": dc["device_code"],
            },
        )
        if status == 200 and "refresh_token" in tok:
            print("\n=== SUCCESS ===")
            print("Save this as the GitHub secret MS_REFRESH_TOKEN:\n")
            print(tok["refresh_token"])
            print("\n(Do not share it. It grants read access to that mailbox.)")
            return 0
        err = tok.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        print(f"\nLogin failed: {tok.get('error_description', tok)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
