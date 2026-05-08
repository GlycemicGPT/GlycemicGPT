# Dev-only utilities

Scripts and helpers for local GlycemicGPT development. None of this is
shipped in any production image — these files live in the repo so
they're reviewable and version-controlled, but they're never copied
into a Dockerfile context.

## Who these scripts are for

GlycemicGPT integrates with Nightscout, and that integration covers
data shapes from many platforms (Loop, AAPS, Trio, oref0, iAPS, xDrip,
LibreLink Up, share2nightscout, tconnectsync, manual care-provider
entry, ...). To validate any code touching that surface against
realistic data, you'd otherwise need:

1. A running Nightscout instance.
2. A real CGM (Dexcom G6/G7) feeding it.
3. A real closed-loop / uploader system pushing treatments and
   devicestatus.
4. Realistically: an actual diabetes diagnosis on the contributor.

That filters down to a tiny pool of contributors. The scripts here
let anyone with a local Nightscout test stack drive the integration
surface without any of (2) – (4). They're test fixtures-as-scripts.

## Which Nightscout test driver should I use?

| | `ns_synthetic_uploader.py` | `ns_emulator.py` |
|---|---|---|
| **Purpose** | "Is data flowing?" smoke test | Per-platform realism |
| **BG model** | Mean-reverting random walk + sine | IoB / COB physiology + meals + corrections |
| **Treatments** | None | Per-lens: meal/correction/temp-basal, suspends, site changes |
| **Devicestatus** | None | Per-lens: full Loop / AAPS / Trio / etc. subtree shape |
| **Profile** | No | Yes, if none exists |
| **Pump status** | n/a | Per-lens: depleting reservoir, draining battery, suspends |
| **Multi-platform** | No | Yes — one lens per real-world platform |
| **When to reach for it** | "Did my scheduler change still tick?" | "Does my translator handle Loop / AAPS / Trio output correctly?" |

If you're not sure, start with `ns_synthetic_uploader.py` — fastest
to spin up. Switch to `ns_emulator.py` the moment you need treatments,
IoB / COB, predicted-glucose curves, pump status, or anything that
should look like a real diabetic on a real platform.

### Prerequisite for both

A local Nightscout test stack reachable on `http://127.0.0.1:1337`
(or wherever you point `NS_BASE_URL`). NOT shipped with GlycemicGPT
— set it up separately with the upstream
[Nightscout docker-compose docs](https://nightscout.github.io/nightscout/new_docker/).

## `ns_synthetic_uploader.py`

Continuously posts synthetic CGM entries (sgv only) to a local
Nightscout. Useful for:

- Watching the Story 43.4 sync scheduler tick → new rows land →
  dashboard chart updates over a few minutes.
- Demoing the data flow without setting up any real CGM/pump.
- Reproducing scheduler / dedupe edge cases.

### Quick start

```bash
# Start the local Nightscout test stack first (lives outside this repo):
cd ~/dev-test/nightscout && docker compose up -d

# Then run the uploader.
NS_API_SECRET="<your-test-stack-secret>" \
  python3 dev/ns_synthetic_uploader.py
```

Stops on Ctrl-C. No backfill — only posts forward in time.

### Tunables (env vars)

| Variable | Default | Purpose |
|---|---|---|
| `NS_BASE_URL` | `http://127.0.0.1:1337` | Nightscout URL |
| `NS_API_SECRET` | **REQUIRED** | Plaintext API_SECRET; SHA-1'd into the api-secret header |
| `NS_CADENCE_SECONDS` | `60` | Seconds between entries |
| `NS_BASELINE_MGDL` | `120` | Mean of the random walk |
| `NS_VOLATILITY` | `5` | Per-step jitter (mg/dL) |
| `NS_DEVICE_NAME` | `glycemicgpt-synthetic-uploader` | `device` field on each entry |

`NS_API_SECRET` is intentionally required (no default) -- baking a
secret-shaped string into source code is bad hygiene.

## `ns_emulator.py`

A multi-lens patient + platform emulator. Pretends to be a real
diabetic running one specific platform that uploads to Nightscout,
and posts continuously the way that platform does. Each "lens" is a
faithful renderer of one platform's actual NS wire format, anchored
to its source-of-truth document in the external
[`bewest/rag-nightscout-ecosystem-alignment`](https://github.com/bewest/rag-nightscout-ecosystem-alignment)
repo.

The architecture splits into:

- **A shared physiology engine** — IoB / COB / dawn / meal / correction
  state machine, driving a continuous stream of "what's happening to
  this simulated patient" events. Same engine for every lens.
- **A `Lens` per platform** — knows that platform's authentication,
  endpoints, identity fields, payload shapes, and quirks.

### Currently shipped lenses

| Lens | Platform | Status | Reference doc |
|---|---|---|---|
| `loop` | Loop on iPhone (NS API v1, SHA-1 secret) | Shipped | `mapping/loop/nightscout-sync.md` |
| `aaps_v1` | AndroidAPS NSClient legacy (NS API v1, SHA-1) | Shipped | `mapping/aaps/nightscout-sync.md` + `mapping/aaps/nsclient-schema.md` |

### Planned lenses (each its own PR)

| Lens | Platform | Reference doc |
|---|---|---|
| `aaps_v3` | AAPS NSClientV3 (NS API v3, JWT) | `mapping/aaps/nightscout-sync.md` |
| `trio` | Trio (NS API v1, oref-derived) | `mapping/trio/nightscout-sync.md` |
| `oref0` | OpenAPS oref0 (raspberry pi) | `mapping/oref0/data-models.md` |
| `iaps` | iAPS (Trio's predecessor) | `mapping/trio/nightscout-sync.md` |
| `xdrip_plus` | xDrip+ (Android, CGM-only) | `mapping/xdrip-android/` |
| `xdrip4ios` | xDrip4iOS (Apple, CGM-only) | `mapping/xdrip4ios/` |
| `librelink_up` | LibreLink Up bridge (Libre 2/3 → NS) | `mapping/nightscout-librelink-up/` |
| `share2ns` | share2nightscout-bridge | `mapping/share2nightscout-bridge/` |
| `tconnectsync` | tconnectsync (Tandem t:connect → NS) | `mapping/tconnectsync/` |
| `manual` | Direct Nightscout web UI entry | `mapping/cgm-remote-monitor/` |

The reference repo is reference, not authoritative — when its claims
and a platform's actual upstream source disagree, the upstream source
wins. Each lens module documents which upstream files it cross-checked.

### Quick start

```bash
NS_API_SECRET="<your-test-stack-secret>" \
  python3 dev/ns_emulator.py --platform loop
```

That runs the default — Loop lens, real-time cadence (one CGM reading
every 5 wall-clock minutes, exactly like a real Loop user), unbounded
duration (Ctrl-C to stop).

### When you need data fast

Set `NS_TIME_COMPRESSION=60` to compress one simulated hour into one
wall-clock minute (a full simulated day in ~24 wall-min):

```bash
NS_API_SECRET="..." \
NS_TIME_COMPRESSION=60 \
NS_DURATION_HOURS=6 \
  python3 dev/ns_emulator.py --platform loop
```

Each entry's `dateString` is the actual wall-clock instant when the
emulator posted it. NS-side timestamps are never future-dated. So
high compression only changes the cadence (many entries in quick
succession — at 60× compression, one every 5 wall-seconds) without
shifting their timestamps off real time. As wall-clock advances,
those entries become "past" relative to whatever query reads them.

### Common tunables (env vars)

| Variable | Default | Purpose |
|---|---|---|
| `NS_BASE_URL` | `http://127.0.0.1:1337` | Nightscout URL |
| `NS_API_SECRET` | **REQUIRED** | Plaintext API_SECRET |
| `NS_PLATFORM` | `loop` | Lens to use; same as `--platform` |
| `NS_TIME_COMPRESSION` | `1` | Sim minutes per wall-clock minute. `1`=realtime; `60`=fast |
| `NS_DURATION_HOURS` | `0` | Sim hours before exit. `0`=unbounded |
| `NS_RANDOM_SEED` | unset | Set int for reproducible runs |
| `NS_STARTING_BG` | `120` | Initial blood-glucose value |

### Per-lens tunables

#### `aaps_v1`

| Variable | Default | Purpose |
|---|---|---|
| `NS_AAPS_UPLOAD_TEMP_BASALS` | `false` | When `true`, the AAPS lens posts a Temp Basal treatment every loop cycle (matches AAPS users who enable "Upload temp basals" in NSClient settings). Default off because survey of real-world AAPS fixtures shows most users keep it off for NS quota / privacy reasons. Turn on for exhaustive temp-basal mapper coverage. |

The AAPS lens emits, on its own schedule:
- **Meal Bolus** + **SMB** treatments (matches real AAPS-SMB user fixture distribution)
- **Manual Correction Bolus** (~20% of corrections, vs SMB ~80%)
- **Temporary Target** once per simulated day (morning exercise window 6-7am, target 140 for 60 min, reason "Exercise")
- **Profile Switch** once per simulated day (afternoon 17-18, "Exercise" profile at 130% for 120 min)
- **Site Change** when reservoir runs low

Bolus payloads carry the AAPS `bolusCalculatorResult` JSON + `isBasalInsulin`, `isSMB`, `type` fields and the AAPS pump-composite dedup triple (`pumpId` / `pumpType` / `pumpSerial`).

The SMB-vs-manual correction split honors `NS_RANDOM_SEED` -- set the seed and the same SMB / manual-bolus distribution will be reproduced on subsequent runs.

### How to verify it actually drove your code

#### One-time setup: connect the API container to the Nightscout network

The local Nightscout test stack runs on its own Docker network
(`nightscout_default`) and isn't reachable from inside the
GlycemicGPT API container by default. Connect it once per dev box:

```bash
docker network connect nightscout_default glycemicgpt-api-1
```

This persists for the life of the API container — only re-run after
you `docker compose down` + `up` the GlycemicGPT stack.

#### Then drive the integration

```bash
# 1. Bring up the GlycemicGPT stack
docker compose up --build -d

# 2. Sign in to the web app, go to Settings → Integrations
# 3. Add a Nightscout connection:
#      URL = http://glycemicgpt-test-nightscout:1337
#      api-secret = same one you used for the emulator
#      sync_interval = 1 min

# 4. Trigger an immediate sync from the UI
# 5. Watch the dashboard widget you're working on populate
```

If a widget renders empty, your code path either (a) doesn't read the
data the lens produced, or (b) doesn't extract it into the right
table. The emulator is doing its job either way.

### What this emulator is NOT

- A control algorithm (it does not advise / dose a real human)
- A CGM replacement
- A production fixture — never imported by application code, never
  copied into a Docker image
- Authoritative — when its modeled behavior diverges from a real
  platform's, the real platform wins
