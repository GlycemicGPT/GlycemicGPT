# GlycemicGPT Medtronic CareLink Connect helper (Go)

A tiny static binary that completes the one-time Medtronic **CarePartner**
login on the user's machine and hands the resulting authorization code to
their GlycemicGPT instance. No Python, no install footprint — the binary lives
**inside the user's own GlycemicGPT** (baked into the API Docker image), is
served by an endpoint that's **only active while a pair token is alive**, and
runs once per setup.

## Why this exists

Medtronic's CarePartner login can only be completed in a browser, and on
success Auth0 redirects to a *mobile-app* URL scheme
(`com.medtronic.carepartner:/sso?code=…`) that no web app and no server can
receive. So a tiny local helper drives the login in the user's own installed
Chromium-family browser, intercepts that redirect at the Chrome DevTools
Protocol layer, and POSTs the code to the user's GlycemicGPT backend. The
backend does the Auth0 token exchange server-side — **the refresh token never
reaches this binary.**

## What it never sees

- The user's CareLink password (typed directly into Medtronic's page).
- The user's GlycemicGPT password (the pair token only authorizes the two
  Connect-handshake endpoints for that one user).
- The Medtronic refresh token (the backend does the exchange).

## How users get it

They never download from us. The web card in GlycemicGPT prints **one** line
of bash/PowerShell pre-filled with their pair token and their instance URL;
that script downloads the right OS-arch binary from their own instance and
runs it. The endpoint serving the binary is gated by the pair token: 404 when
no active pairing, 404 when expired, 404 the instant `/exchange` succeeds.

## Build

The multi-stage `apps/api/Dockerfile` compiles per-OS binaries on image build
and copies them into `/app/connect-helper-dist/{os}/{arch}/`. Targets:

- `linux/amd64`, `linux/arm64`
- `darwin/amd64`, `darwin/arm64`
- `windows/amd64`

To build locally for development:

```
cd tools/connect-helper
go mod tidy
go build -o glycemicgpt-connect .
go test ./...
```

## CLI flags

| Flag | Default | Purpose |
|---|---|---|
| `--api`      | (required) | Your GlycemicGPT base URL (the same URL you used to reach the dashboard). |
| `--pair`     | (required) | Pair token rendered by the GlycemicGPT web card. |
| `--username` | (required) | Your CareLink username. |
| `--region`   | `US`       | `US`, or `EU` for any non-US account (UK/EU/AU/ZA/…). |
| `--timeout`  | `5m`       | How long to wait for the human to finish the browser login. |
| `--headless` | off        | Don't use — CarePartner requires a captcha. |

## Browser requirement

Chrome, Edge, Brave, or Chromium installed locally. Firefox-only users get a
clear error message; Firefox support (via Marionette) is a follow-up.

## Scope (v1)

This helper connects the user's **own** Medtronic account (the `patient` role).
The **follower / care-partner** case — logging in to follow someone else's pump
— additionally needs `role` and `patient_id` in the exchange payload (the
backend `/exchange` already accepts them) plus a way to choose the patient.
That's a tracked follow-up, not in v1.

## Source of truth

This binary speaks two GlycemicGPT endpoints, exactly the same ones the Python
`tools/medtronic-connect-login/` CLI hits:
`GET /api/integrations/medtronic/connect/authorize-url` and
`POST /api/integrations/medtronic/connect/exchange`. Both accept the helper's
pair token via the `X-Connect-Pair-Token` header.
