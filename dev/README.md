# Dev-only utilities

Scripts and helpers that exist for local development workflows. None of
this is shipped in any production image — these files live in the repo
so they're reviewable and version-controlled, but they're never copied
into a Dockerfile context.

## Which Nightscout test driver should I use?

Two scripts are available, with different goals:

| | `ns_synthetic_uploader.py` | `ns_realistic_emulator.py` |
|---|---|---|
| Purpose | Quick "data flows" smoke test | Full-realism patient simulation |
| BG model | Mean-reverting random walk + sine | IoB / COB physiology + meals + corrections |
| Treatments emitted | None | `Meal Bolus`, `Correction Bolus` |
| Devicestatus emitted | None | Loop-shaped subtree (iob, cob, predicted, enacted) |
| Profile posted | No | Yes, if none exists |
| Best for | Fastest path to "is the scheduler ticking?" | Exercising closed-loop fields, dashboard widgets, dedupe / freshness math against realistic data shapes |

Use `ns_synthetic_uploader.py` when you just need any data flowing.
Use `ns_realistic_emulator.py` when verifying widgets that read
treatments, IoB/COB, or predicted-glucose state — i.e. anything that
should look like a real Loop / iAPS user on the dashboard.

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

# Then run the uploader. NS_API_SECRET is required -- whatever you
# set as the API_SECRET env var on the NS container.
NS_API_SECRET="<your-test-stack-secret>" \
  python3 dev/ns_synthetic_uploader.py
```

Stops on Ctrl-C. No backfill — only posts forward in time.

### Tunables (env vars)

| Variable | Default | Purpose |
|---|---|---|
| `NS_BASE_URL` | `http://127.0.0.1:1337` | Nightscout URL |
| `NS_API_SECRET` | **REQUIRED** (no default) | Plaintext API_SECRET; SHA-1'd into the api-secret header |
| `NS_CADENCE_SECONDS` | `60` | Seconds between entries |
| `NS_BASELINE_MGDL` | `120` | Mean of the random walk |
| `NS_VOLATILITY` | `5` | Per-step jitter (mg/dL) |
| `NS_DEVICE_NAME` | `glycemicgpt-synthetic-uploader` | `device` field on each entry |

`NS_API_SECRET` is intentionally required (no default). Even though
this script only talks to a local-only test instance, baking a
secret-shaped string into source code is bad hygiene — it gets
flagged by secret scanners, leaks into deploy contexts that
shouldn't have dev-only constants, and obscures genuine
misconfiguration.

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

## `ns_realistic_emulator.py`

Drives the same local Nightscout instance with data that looks like a
real Loop / iAPS user's day: meals at meal times, post-meal BG rises,
insulin lowering BG over its duration of action, dawn phenomenon,
correction boluses on persistent highs, and Loop-shaped devicestatus
on every reading.

### Why this exists

The simple uploader random-walks a single SGV value, which is fine for
"is the scheduler ticking?" but doesn't exercise the closed-loop
plumbing — `loop_subtree_json`, predicted-BG curves, IoB/COB,
treatments, dedupe across overlapping bolus records — and the
resulting dashboard charts look mechanical rather than physiological.
This script outputs continuous data that matches what the integration
will see in production.

### Quick start

```bash
NS_API_SECRET="<your-test-stack-secret>" \
  python3 dev/ns_realistic_emulator.py
```

Defaults run at 10× time compression: ~30 seconds of wall-clock per
"5 simulated minutes," so a full simulated day lands in ~144
wall-minutes (~2.4 hours). For a faster sweep set
`NS_TIME_COMPRESSION=60` (one simulated day in ~24 wall-minutes) or
`NS_DURATION_HOURS=4` to cap the run. The dashboard's recent-window
views see fresh data arriving continuously, and treatments /
devicestatus appear at the same cadence Loop posts them.

Stops on Ctrl-C. No state persistence — restart starts a fresh patient.

### Tunables (env vars)

| Variable | Default | Purpose |
|---|---|---|
| `NS_BASE_URL` | `http://127.0.0.1:1337` | Nightscout URL |
| `NS_API_SECRET` | **REQUIRED** | Plaintext API_SECRET; SHA-1'd into the api-secret header |
| `NS_TIME_COMPRESSION` | `10` | Sim minutes per wall-clock minute. `1` = realtime; `60` = "an hour every minute" |
| `NS_DURATION_HOURS` | `24` | Simulated hours before the loop exits. `0` = unbounded |
| `NS_DEVICE_NAME` | `loop://iPhone/realistic-emulator` | `device` field on entries / devicestatus |
| `NS_STARTING_BG` | `120` | Initial blood-glucose value |
| `NS_PROFILE_NAME` | `Default` | Profile name written if none exists |
| `NS_RANDOM_SEED` | unset | Set to an int for reproducible runs |

### What gets emitted per simulated 5-minute tick

- **One CGM entry** (`/api/v1/entries.json`, type `sgv`) with `direction`
  derived from the BG delta.
- **One devicestatus** (`/api/v1/devicestatus.json`) with a Loop subtree:
  `iob`, `cob`, a 6-hour `predicted` curve, `recommendedBolus`, and an
  `enacted` basal record.
- **Meal Bolus treatments** at meal-time hours (7-9, 12-13, 18-20
  simulated time), carrying both carbs and the matching insulin dose.
- **Snack treatments** mid-morning / mid-afternoon, smaller and rarer.
- **Correction Bolus treatments** when BG sits above 200 mg/dL with
  insufficient IoB (90-min cooldown so the model doesn't stack).

On startup, the script posts a profile snapshot if none already exists,
which lets the onboarding flow read its ISF / ICR / basal defaults.

### Physiology assumptions

These are realistic adult defaults; the constants are at the top of
the script if you want to vary them:

- ISF: 50 mg/dL/U
- ICR: 10g/U
- DIA: 4 hours (linear decay; not bi-exponential)
- Carb absorption window: 90 min (linear)
- Basal: 0.8 U/hr
- Target: 110 mg/dL
- BG clamp: 40-400 mg/dL
- Dawn phenomenon: 4-7 am, peaking ~8 mg/dL/hr at the strongest

Linear insulin / carb decay is a simplification — real curves peak
around 60-90 min — but the resulting BG traces look correct on the
chart and the closed-loop fields receive realistic values, which is
what the dashboard widgets need to render properly.
