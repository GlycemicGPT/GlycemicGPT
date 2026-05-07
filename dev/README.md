# Dev-only utilities

Scripts and helpers that exist for local development workflows. None of
this is shipped in any production image — these files live in the repo
so they're reviewable and version-controlled, but they're never copied
into a Dockerfile context.

## Who are these scripts for?

GlycemicGPT integrates with Nightscout, Loop, AAPS, and iAPS. To
validate any code that touches that surface end-to-end against a
real Nightscout deployment, you'd otherwise need:

1. A running Nightscout instance (Mongo + Node, separately deployed).
2. A real CGM (Dexcom G6/G7) feeding it.
3. A real closed-loop system (Loop on iPhone, AAPS on Android,
   iAPS) generating treatments, devicestatus, and profile data.
4. Realistically: an actual diabetes diagnosis on the contributor.

That filters down to a tiny pool of contributors. These two scripts
let anyone with a local Nightscout test stack drive that integration
surface without any of (2)-(4). They're test fixtures-as-scripts.

## Which Nightscout test driver should I use?

| | `ns_synthetic_uploader.py` | `ns_realistic_emulator.py` |
|---|---|---|
| **Purpose** | "Is data flowing?" smoke test | Full-realism patient simulation |
| **BG model** | Mean-reverting random walk + sine | IoB / COB physiology + meals + corrections |
| **Treatments** | None | `Meal Bolus`, `Correction Bolus` |
| **Devicestatus** | None | Loop-shaped subtree (iob, cob, predicted, enacted) |
| **Profile** | No | Yes, if none exists |
| **When to reach for it** | "Did my scheduler change still tick?" "Did the entries route still work?" | "Does my IoB widget render the right value?" "Does my AGP chart look like a real patient?" "Does my dedupe handle Loop's overlapping bolus records?" |

If you're not sure, start with `ns_synthetic_uploader.py` — it's
faster to spin up. Switch to `ns_realistic_emulator.py` the moment
you need a treatment, an IoB number, a predicted-BG curve, or
anything that should look like a real Loop / iAPS user.

### Prerequisite for both

A local Nightscout test stack reachable on `http://127.0.0.1:1337`
(or wherever you point `NS_BASE_URL`). This is NOT shipped with
GlycemicGPT — set it up separately with Mongo + Nightscout's own
docker-compose. If you don't have one yet, see the upstream
[Nightscout docker-compose docs](https://nightscout.github.io/nightscout/new_docker/).
Once it's up, point either script at it.

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

A patient-physiology state machine that posts continuous Loop-shaped
data to a local Nightscout instance. Lets you exercise the parts of
the GlycemicGPT integration that only fire on realistic data: IoB
display, COB display, predicted-glucose curves, AGP charts,
treatments tables, dedupe across overlapping bolus records, the
per-source freshness widget, the Insulin Summary panel.

### When to use it

- You're working on a dashboard widget that reads anything beyond
  an `sgv` value. (CGM Summary, IoB, AGP, Bolus Review, Insulin
  Summary, predicted-BG, freshness.)
- You're touching the Nightscout translator
  (`apps/api/src/services/integrations/nightscout/translator.py`)
  and want to validate the round trip.
- You're modifying the bolus-dedupe CTE or any code that reads
  `loop_subtree_json` / `openaps_subtree_json`.
- You're demoing a feature that should "look like a real patient"
  on the dashboard.

### When NOT to use it

- You only need "is the scheduler ticking?" → use
  `ns_synthetic_uploader.py`, it's faster to spin up.
- You're testing application code that doesn't touch Nightscout at
  all. (Auth, AI chat, mobile-app local data, Tandem BLE, ...)
- You're trying to test edge cases the model doesn't simulate
  (sensor failures, Bluetooth dropouts, double-bolus user errors).
  For those, post hand-crafted treatments directly to the NS API
  rather than reaching for this script.

### Why it exists

The simpler `ns_synthetic_uploader.py` random-walks a single SGV
value — fine for smoke tests but doesn't exercise the closed-loop
plumbing (`loop_subtree_json`, predicted-BG, IoB / COB, treatments,
dedupe). Without this script, validating any of those code paths
end-to-end requires a real Loop / iAPS / AAPS user feeding a real
Nightscout, which is impractical for most contributors. This script
fills that gap.

### How to run it

You need:

1. The local Nightscout test stack already running. Confirm with
   `curl http://127.0.0.1:1337/api/v1/status.json` — should return 200.
2. The `API_SECRET` you set on that stack.

Then:

```bash
NS_API_SECRET="<your-test-stack-secret>" \
  python3 dev/ns_realistic_emulator.py
```

That runs the default — 24 simulated hours at 10× compression, which
takes ~144 wall-clock minutes (~2.4 h). For most derisks you want a
faster run; set `NS_DURATION_HOURS=6` and `NS_TIME_COMPRESSION=60`
to land 6 simulated hours in ~6 wall-minutes, with full meal + bolus
+ correction coverage:

```bash
NS_API_SECRET="<your-test-stack-secret>" \
NS_TIME_COMPRESSION=60 \
NS_DURATION_HOURS=6 \
  python3 dev/ns_realistic_emulator.py
```

Stops on Ctrl-C. No state persistence — restart starts a fresh
patient. To keep two derisk runs identical, pass `NS_RANDOM_SEED`.

### How to verify it actually drove your code

After a run, point the GlycemicGPT API at the same NS instance:

1. Bring up the GlycemicGPT stack: `docker compose up --build -d`
2. Sign in to the web app, go to `Settings → Integrations`.
3. Add a Nightscout connection: URL = `http://host.docker.internal:1337`
   (or your host's IP from inside the API container), `API_SECRET` =
   the same one you used for the emulator, sync interval = 1 min.
4. Trigger an immediate sync from the UI, then go to the dashboard.
5. The widget you're working on should populate from emulator data.

If a widget renders empty, that's the signal your code path isn't
reading the data the emulator generated — debug from there.

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
