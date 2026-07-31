# Read the certificate@ mailbox (Microsoft Graph) — one-time setup

The **Poll completions** workflow reads the dedicated
`certificate@aaimpactinc.com` inbox every ~15 minutes, finds Zoho's
"*&lt;Learner&gt; has completed course &lt;Course&gt;.*" emails, and issues + emails the
certificates. No Power Automate / premium needed.

You do this once: register an Azure app, mint a refresh token for that mailbox,
and add three GitHub secrets. (Same idea as the Zoho refresh token.)

## 1. Register an Azure app

1. **portal.azure.com** → **Microsoft Entra ID** (Azure AD) → **App
   registrations** → **New registration**.
   - Name: `AA Impact certificate mailbox reader`
   - Supported account types: **Single tenant**
   - Redirect URI: leave blank → **Register**.
2. On the app's **Overview**, copy **Application (client) ID** and **Directory
   (tenant) ID**.
3. **Authentication** → scroll to **Advanced settings** → set **Allow public
   client flows** = **Yes** → **Save**. (Required for the device-code login.)
4. **API permissions** → **Add a permission** → **Microsoft Graph** →
   **Delegated permissions** → check **Mail.Read** (and **offline_access** if
   listed) → **Add**. Then **Grant admin consent** for your tenant.

This grants read access to only the mailbox you sign in as (below) — least
privilege.

## 2. Mint the refresh token (sign in as certificate@)

On your computer (needs Python):

```bash
python scripts/ms_device_login.py --tenant YOUR_TENANT_ID --client YOUR_CLIENT_ID
```

It prints a URL + code. Open the URL, enter the code, and **sign in as
certificate@aaimpactinc.com**. It then prints a **refresh token** — copy it.

## 3. Add GitHub secrets

Settings → Secrets and variables → Actions:

| Secret | Value |
| --- | --- |
| `MS_TENANT_ID` | Directory (tenant) ID |
| `MS_CLIENT_ID` | Application (client) ID |
| `MS_REFRESH_TOKEN` | the refresh token from step 2 |

(`MS_CLIENT_SECRET` is only needed if you registered a confidential client — the
public-client device flow above doesn't use one.)

The Zoho, Supabase and Resend secrets from the other guides must also be set —
the poller uses Zoho to resolve the learner's email and the rest to issue+email.

## 4. Test it

Repo → **Actions → Poll completions → Run workflow** → set **Dry run** = true
(optionally raise **lookback** hours to reach an older completion email). The log
should list the completion emails found and resolve each learner's email. Untick
dry-run for a real run; after that the every-15-minutes schedule takes over.

## Notes

- **Idempotent**: overlapping poll windows are safe — anyone already holding the
  certificate is skipped.
- **Cadence**: change the `cron` in `.github/workflows/poll-completions.yml`
  (default `*/15 * * * *`).
- **Token lifetime**: the refresh token stays valid as long as it's used
  regularly (the 15-min poll keeps it alive). If it's ever revoked (password
  reset, Conditional Access), re-run step 2 and update `MS_REFRESH_TOKEN`.
- If your tenant blocks device-code sign-in via Conditional Access, tell me and
  I'll switch the app to a confidential client + auth-code flow.
