# glooko-capture

A re-runnable Glooko wire-protocol capture helper for **Story 47.A** (Epic 47 — Omnipod
Cloud Sync via Glooko). It logs in to a real Glooko account, enumerates the reachable
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
# Wide default window (last ~3 years, US cluster) — locates where Omnipod-5 records cluster
uv run tools/glooko-capture/capture.py

# Target a specific historical window (AC2c: is the old Omnipod-5 data still API-reachable?)
uv run tools/glooko-capture/capture.py --start 2023-06-01 --end 2024-03-01

# EU cluster (fragile — nightscout-connect issue #14 saw a 422); show full first records
uv run tools/glooko-capture/capture.py --region EU --show-values
```

`uv` resolves the inline PEP-723 dependency (`httpx`) automatically; no virtualenv setup.

### Flags

| Flag | Default | Purpose |
|---|---|---|
| `--region {US,EU}` | `US` | Regional cluster. EU sets the `Host: eu.api.glooko.com` header. |
| `--host-header` | (auto) | Override the `Host` header (EU edge quirk). |
| `--start YYYY-MM-DD` | `end - days` | Window start. **Use this for the AC2c historical probe.** |
| `--end YYYY-MM-DD` | today (UTC) | Window end. |
| `--days N` | `1095` | Lookback when `--start` is omitted (wide net). |
| `--limit N` | `500` | Per-endpoint record cap. |
| `--out DIR` | `./.captures` | Raw-dump dir (gitignored, PHI). |
| `--show-values` | off | Include full first-record values (PHI) in output. |

## What it probes

- **AC1 — auth:** `POST /api/v2/users/sign_in` with `{userLogin:{email,password}, deviceInformation:{deviceModel:"iPhone"}}`; reports status, `set-cookie` shape, the session cookie, and the patient-id candidates found in the body.
- **AC2 / AC2c — coverage + historical reachability:** hits the three Discovery-confirmed core endpoints plus a **guessed probe set** (pod-change / reservoir / IOB / device-inventory / merged-sync / bulk-export routes) over an **explicit `startDate`/`endDate`** window, recording the status of each so we can state definitively what exists (200) vs is absent (404) vs gated (401/403).
- **AC2d — device/source tagging:** detects device/source/model fields on each record and lists their distinct values across the batch (reveals Omnipod-vs-Tandem mixing).
- **AC4 — shape/units/tz:** records field names + types, timestamp fields (with sample values, for offset handling), and unit fields.
- **AC3 — bulk export:** probes report/export-job candidate routes.

Output: per-endpoint raw JSON under `--out`, plus a `_results.json` rollup that feeds
`_bmad-output/planning-artifacts/glooko-reverse-engineering.md` (AC7).

## ToS note

Glooko's ToS prohibit reverse-engineering and bypassing access measures, and reserve
account termination. This helper is intended for the operator's **own** account, used
knowingly. The account-ban risk is real and is documented in the findings doc so the
eventual consent UX is honest.
