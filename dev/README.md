# Dev-only utilities

Scripts and helpers that exist for local development workflows. None of
this is shipped in any production image — these files live in the repo
so they're reviewable and version-controlled, but they're never copied
into a Dockerfile context.

## `ns_synthetic_uploader.py`

Continuously posts synthetic CGM entries to a local Nightscout instance
so the GlycemicGPT scheduler / dashboard can be visually verified
against "new data arriving in real time" instead of static fixture
data. Useful for:

- Watching the Story 43.4 sync scheduler tick → new rows land →
  dashboard chart updates over a few minutes.
- Demoing the full data flow without setting up a real Dexcom uploader.
- Reproducing scheduler / dedupe edge cases that only show up when new
  entries are arriving on a cadence.

### Quick start

```bash
# Start the local Nightscout test stack first (lives outside this repo):
cd ~/dev-test/nightscout && docker compose up -d

# Then run the uploader from anywhere; it talks to NS over 127.0.0.1:1337
python3 dev/ns_synthetic_uploader.py
```

Stops on Ctrl-C. No backfill — only posts forward in time.

### Tunables (env vars)

| Variable | Default | Purpose |
|---|---|---|
| `NS_BASE_URL` | `http://127.0.0.1:1337` | Nightscout URL |
| `NS_API_SECRET` | the dev-stack secret | Plaintext API_SECRET; SHA-1'd into the api-secret header |
| `NS_CADENCE_SECONDS` | `60` | Seconds between entries |
| `NS_BASELINE_MGDL` | `120` | Mean of the random walk |
| `NS_VOLATILITY` | `5` | Per-step jitter (mg/dL) |
| `NS_DEVICE_NAME` | `glycemicgpt-synthetic-uploader` | `device` field on each entry |

### Implementation notes

- Mean-reverting random walk biased by a 24-hour sine wave so the curve
  doesn't drift in one direction.
- Direction (trend arrow) computed from the per-step delta, mapped to
  Dexcom's `DoubleUp` / `SingleUp` / `FortyFiveUp` / `Flat` /
  `FortyFiveDown` / `SingleDown` / `DoubleDown` vocabulary.
- Stdlib only (no httpx / requests) so the script runs from any
  environment with Python 3.11+.
- Errors are logged and swallowed — the loop never exits on a transient
  upstream failure; it just retries on the next cadence tick.
