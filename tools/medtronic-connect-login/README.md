# Medtronic CareLink Connect — local login helper

A one-time desktop helper that connects your Medtronic CareLink **CarePartner**
account to GlycemicGPT for automatic background sync.

## Why a local tool?

Medtronic's CarePartner login can only be completed interactively in a browser
(with a reCAPTCHA), and on success it redirects to a mobile-app URL scheme
(`com.medtronic.carepartner:`) that a server cannot receive. This helper runs
that login in a real browser on your machine, captures the resulting one-time
authorization **code**, and hands it to **your** GlycemicGPT server, which
exchanges it for the long-lived sync credential and stores it server-side.

After this one-time step, GlycemicGPT renews and syncs entirely on the backend —
you don't run this again unless your CareLink session is fully revoked.

## What it never sees

- **Your CareLink password** — you type it directly into Medtronic's page.
- **Your GlycemicGPT password** — you authenticate with a short-lived *pairing
  token* you copy from the GlycemicGPT web UI.
- **The Medtronic refresh token** — the backend does the code→token exchange;
  the credential is created and stored on your server, never on this machine.

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) (recommended) or Python 3.10+ with `pip`.
- A one-time browser install:
  ```
  playwright install chromium
  ```
  (With `uv`, run the script once — it installs `playwright` — then run the line
  above so the browser binary is present.)

## Usage

1. In GlycemicGPT: **Settings → Integrations → Cloud Sync → Medtronic CareLink →
   "Connect with the desktop helper"**. Copy the **pairing token** (valid ~15
   minutes).
2. Run it from the repo root:
   ```
   uv run tools/medtronic-connect-login/medtronic_connect_login.py \
     --api https://your-glycemicgpt-instance \
     --pair <PAIRING_TOKEN> \
     --username <YOUR_CARELINK_USERNAME>
   ```
   (Or `cd tools/medtronic-connect-login` and run `uv run medtronic_connect_login.py …`.
   Self-hosting on the same machine? Use `--api http://localhost:3000`.)
3. A browser opens. **Sign in to CareLink and solve the captcha.** When it
   succeeds, the helper captures the code, finishes on your server, and prints
   `✓ Connected`. You can close the browser.

## Options

| Flag | Default | Notes |
|---|---|---|
| `--api` | (required) | Your GlycemicGPT base URL. **Point this only at your own instance** — the pairing token is sent here. (It's encrypted to your server, so it's useless elsewhere, but don't paste someone else's URL.) |
| `--pair` | (required) | Pairing token from the GlycemicGPT UI |
| `--username` | (required) | Your CareLink username |
| `--region` | `US` | `US` or `EU`. `EU` covers all non-US CarePartner countries (UK/GB, EU member states, AU, ZA, …) — they share Medtronic's single OUS Auth0 tenant. |
| `--timeout` | `300` | Seconds to wait for you to finish the browser login |
| `--headless` | off | Not recommended — you must solve a captcha |

## Troubleshooting

- **"Pairing token rejected or expired"** — reissue it in the GlycemicGPT UI
  (tokens are short-lived) and run again.
- **"Timed out waiting for sign-in"** — complete the login faster; the
  authorization code is short-lived.
- **No browser opens / Playwright error** — run `playwright install chromium`.
