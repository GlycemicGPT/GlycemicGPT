# glooko-capture

A re-runnable Glooko wire-protocol capture helper for the Omnipod Cloud Sync via Glooko
integration. It logs in to a real Glooko account, enumerates the reachable
`/api/v2` endpoints, and captures the CGM / basal / bolus payloads so the protocol can be
re-verified in minutes instead of re-discovered.

This is the Glooko analogue of `tools/connect-helper` (Medtronic). It is **Python, not Go**,
because Glooko's personal-account flow is a plain credential replay — no browser, no Auth0,
no captcha — so there is nothing for chromedp to drive.

## Why a helper and not just notes

The upstream Glooko driver is marked *Experimental* and the protocol may drift. A
re-runnable capture lets us confirm the wire format against the live API on demand.

## License / clean-room posture

`nightscout/nightscout-connect` (Glooko driver) and `jpollock/glooko2nightscout-bridge`
are **AGPL-3.0**. This helper is a **clean-room** reimplementation written from the
documented protocol facts; **no AGPL code is copied**. Those projects are credited as the
prior art that revealed the endpoint/parameter vocabulary. (AGPL restricts copying code,
not learning a wire protocol.) Attribution is mandatory — see the project OSS-attribution
rule used for `carelink-python-client`.

## Credentials (hard rule)

Credentials are read **at runtime from the environment only**:

```bash
export GLOOKO_EMAIL='you@example.com'
export GLOOKO_PASSWORD='...'        # or supply via `op run`
```

They are **never** an argument default, **never** written to a file, and **never** echoed
(email and all cookie/token values are masked in stdout). Do not put the password on the
command line — argv is visible in the process table.

## PHI / output

Raw API responses contain **your own health data**. They are written only to a
**gitignored** local directory (default `./.captures`) for analysis and **must never be
committed** (the local `.gitignore` enforces this). Stdout prints redacted *shape*
summaries (field names + types, plus timestamp/unit/device sample values needed for the
protocol facts) — not glucose/insulin values, unless you pass `--show-values`.

## Usage

```bash
# US, web-session login, one cursor page per stream (shape capture)
uv run tools/glooko-capture/capture.py

# Walk several cursor pages (history goes back to ~2023 on a real account)
uv run tools/glooko-capture/capture.py --max-pages 5

# Replay a session cookie copied from a logged-in browser instead of logging in
GLOOKO_SESSION_COOKIE=... uv run tools/glooko-capture/capture.py --auth cookie

# EU cluster (fragile — nightscout-connect issue #14 saw a 422); show full records
uv run tools/glooko-capture/capture.py --region EU --show-values
```

`uv` resolves the inline PEP-723 dependency (`httpx`) automatically; no virtualenv setup.

### Flags

| Flag | Default | Purpose |
|---|---|---|
| `--region {US,EU}` | `US` | Regional cluster (region-PREFIXED `us.`/`eu.` hosts). EU is known-fragile. |
| `--auth {web,cookie}` | `web` | `web` = the Devise form login; `cookie` = replay `GLOOKO_SESSION_COOKIE`. |
| `--max-pages N` | `1` | Keyset-cursor pages to walk per stream (1 = shape only; raise to walk history). |
| `--out DIR` | `./.captures` | Raw-dump dir (gitignored, PHI). A path **outside** the tool dir is warned about. |
| `--show-values` | off | Include full record values (PHI) in output. |

## What it does

- **Auth:** the **web Devise session** flow — GET `us.my.glooko.com/users/sign_in` (CSRF + cookie) → form-POST the login → replay the `_logbook-web_session` cookie on `us.api.glooko.com`. (The mobile `POST /api/v2/users/sign_in` is a dead end for web-only accounts — see `capture.py` header.) `--auth cookie` skips the login and replays a cookie you supply.
- **Discovery:** confirms the session via `/api/v3/session/users`, extracts the patient slug, and reads `/api/v3/end_dates` + `/api/v3/devices_and_settings` (device inventory).
- **Pump data:** drains the `/api/v2/*` keyset-cursor streams (`pumps/scheduled_basals`, `pumps/normal_boluses`, `pumps/events`, `pumps/modes`, `pumps/alarms`, `cgm/readings`, `cgm/egvs`, …) using `lastUpdatedAt`+`lastGuid`, printing per-stream record counts + the historical span + distinct device/event-type values.
- **CGM glucose:** queries `/api/v3/graph/statistics/overall` (the v3-graph path — CGM is not in the v2 cursor) to confirm glucose presence + units.

Output: per-stream raw JSON under `--out`, plus a `_results.json` rollup that documents
the observed Glooko protocol.

## A note on Glooko

Glooko has no official API, so this helper signs in with the operator's own
credentials the way the website does — it's an unofficial connection. It's
intended for the operator's **own** account, used knowingly; never point it at an
account you don't own.
