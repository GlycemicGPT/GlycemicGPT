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
| `aaps_v3` | AndroidAPS NSClientV3 (NS API v3, JWT subject) | Shipped | `mapping/aaps/nightscout-sync.md` + `mapping/aaps/nsclient-schema.md` |
| `trio` | Trio (iOS oref-derived, NS API v1, SHA-1) | Shipped | `mapping/trio/nightscout-sync.md` + `mapping/trio/data-models.md` |
| `oref0` | OpenAPS oref0 (Raspberry Pi, NS API v1, SHA-1) | Shipped | `mapping/oref0/data-models.md` + upstream `openaps/oref0:bin/ns-status.js` |
| `xdrip4ios` | xDrip4iOS (Apple, pure-CGM uploader) | Shipped | `mapping/xdrip4ios/` + upstream `JohanDegraeve/xdripswift` |

### Planned lenses (each its own PR)

| Lens | Platform | Reference doc |
|---|---|---|
| `iaps` | iAPS (Trio's predecessor) | `mapping/trio/nightscout-sync.md` |
| `xdrip_plus` | xDrip+ (Android, CGM-only) | `mapping/xdrip-android/` |
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

#### `aaps_v3`

The NSClientV3 lens emits the same AAPS event shapes as `aaps_v1` --
Meal Bolus, SMB, Correction Bolus, Temp Basal (gated by
`NS_AAPS_UPLOAD_TEMP_BASALS` exactly like v1), Site Change,
Temporary Target, Profile Switch, plus the same physiology-driven
schedule. The differences are all transport / identity:

- **Auth**: instead of the SHA-1 `api-secret` header, this lens
  bootstraps a NS subject named `aaps-v3-emulator` (idempotent --
  reuses the existing subject if present), exchanges its access
  token for a JWT via `/api/v2/authorization/request/<token>`, and
  sends `Authorization: Bearer <jwt>`. JWT is auto-refreshed before
  expiry. The bootstrap requires admin permissions, which the
  api-secret SHA-1 grants to the `/api/v2/authorization/subjects`
  endpoint -- no manual NS Admin Tools setup required.
- **Endpoints**: posts to `/api/v3/{entries,treatments,devicestatus,profile}`
  (without the `.json` suffix v1 uses), one document per request.
- **Wire format additions**: every record carries a
  client-generated UUID `identifier`, dual `date` / `mills`
  epoch-ms timestamps, integer `utcOffset` (minutes), `app: "AAPS"`,
  and the immutability / soft-delete flags `isReadOnly: false` /
  `isValid: true`. NS-set fields (`srvCreated`, `srvModified`,
  `subject`) appear on the response and via subsequent reads.
- **Same identity for pump events**: AAPS still uses the
  `pumpId` / `pumpType` / `pumpSerial` triple inside the body --
  that's orthogonal to the NS `identifier`.

Per-record fields are observable via either `/api/v3/...` reads
(JWT) or `/api/v1/*.json` reads (api-secret) -- both return the
same MongoDB documents with the v3 fields preserved. The
GlycemicGPT translator currently reads via v1, so this lens drives
the same translator code paths the v1 lens does, plus the v3 wire
format end-to-end.

There are no `aaps_v3`-specific tunables. `NS_AAPS_UPLOAD_TEMP_BASALS`
and `NS_RANDOM_SEED` work identically to `aaps_v1` (the v3 lens
inherits the v1 lens, overriding only auth + endpoints).

#### `trio`

The Trio lens emits the iOS oref-derived wire format. There are no
`trio`-specific tunables; it honors `NS_RANDOM_SEED` for the SMB-
vs-manual correction split. Real Trio behaviors this lens models:

- **`enteredBy: "Trio"` only** -- no `device` field on individual
  treatments (only on devicestatus). No `app` field anywhere
  (Trio doesn't send one over NS API v1).
- **Bolus eventType is `"Bolus"` or `"SMB"`** -- per upstream
  `determineBolusEventType` (`Trio/Sources/APS/Storage/PumpHistoryStorage.swift`),
  Trio does NOT distinguish meal-bolus from manual-correction-bolus
  on the wire. `"Meal Bolus"` / `"Correction Bolus"` enum cases
  exist for inbound parsing of foreign uploaders' records but Trio
  itself never emits them.
- **Carbs are a separate `"Carb Correction"` treatment** posted at
  the same `created_at` as the meal bolus (NOT bundled into one
  Meal Bolus document like AAPS does). Includes `fat` and `protein`
  macros (FPU support).
- **Client-generated UUID `id`** on every treatment for dedupe
  (Trio queries with `find[id][$eq]=...`). No `pumpId` /
  `pumpType` / `pumpSerial` triple.
- **devicestatus** carries `openaps + pump + uploader`, NO
  `configuration` subtree. `uploader` is a NESTED object
  Loop-style. Upstream Trio's shape is
  `{batteryVoltage?, battery, isCharging?}`; this lens emits
  only `{battery, isCharging}` because `PatientState` doesn't
  model phone battery voltage. AAPS-style top-level
  `uploaderBattery` int is NOT used. `pump` carries
  `bolusIncrement`.
- **`enacted.received`** is correctly spelled (lowercase, no typo).
- **Determination JSON** uses CAPITAL keys (`IOB`, `COB`, `ISF`,
  `CR`, `TDD`, `predBGs.{IOB,COB,UAM,ZT}`) per the oref0 wire
  convention.
- **Profile** carries Trio-specific iOS fields
  (`bundleIdentifier`, `deviceToken`, `isAPNSProduction`,
  `overridePresets`, `teamID`) -- emitted as placeholders.

Cross-checked against upstream Trio source files
(`Trio/Sources/Models/{NightscoutTreatment,NightscoutStatus,Determination}.swift`,
`Trio/Sources/APS/Storage/{PumpHistoryStorage,CarbsStorage}.swift`)
rather than relying solely on the reference repo -- the reference
repo's note about a `recieved` typo turned out to be stale; upstream
uses `received` correctly.

#### `oref0`

The oref0 lens emits the bare original oref-family wire format. oref0
is the Raspberry Pi command-line implementation that AAPS, iAPS, and
Trio all forked from -- so its wire shape is the *least* embellished
of the family.

| Variable | Default | Purpose |
|---|---|---|
| `NS_OREF0_HOSTNAME` | `openaps-emulator` | Hostname stamped into `device: "openaps://<hostname>"` on devicestatus. Default is fixed so runs are review-friendly under a known `NS_RANDOM_SEED`. Set to override (e.g., your actual Pi's hostname) when stress-testing the translator's `parse_openaps_uri` heuristic against varied real-world inputs. |

`NS_RANDOM_SEED` is honored for the SMB-vs-manual correction split.

Real oref0 behaviors this lens models:

- **Identity**: `device: "openaps://openaps-emulator"` on
  devicestatus (scheme + hostname only, no path; upstream
  `bin/ns-status.js` emits `"openaps://" + os.hostname()` -- this
  lens substitutes the fixed `openaps-emulator` hostname for
  run-to-run determinism). `enteredBy: "openaps://medtronic/722"`
  on every treatment (scheme + hostname + a `/<model>` path
  component, per upstream `bin/mm-format-ns-treatments.sh` which
  stamps `openaps://medtronic/<model>` on every algorithm-driven
  upload; `722` is a popular Medtronic model in oref0 deployments).
  The reference repo's claim of bare `"openaps"` as enteredBy
  literal turned out to be stale; upstream's pump-driver pipeline
  uses the URI form. Care Portal manual entries on real oref0
  boxes can have blank or bare `"openaps"` enteredBy, but the
  algorithm-driven upload path (which is what this lens emulates)
  uses the URI form.
- **Bolus eventType PRESERVES the Meal/Correction distinction**:
  `"Meal Bolus"` (insulin from a wizard-calculated meal dose),
  `"Correction Bolus"` (manual user correction), `"SMB"` (algorithm
  micro-bolus). Trio collapsed Meal/Correction into a generic
  `"Bolus"`; oref0 does NOT.
- **Carbs are a separate `"Carb Correction"` treatment** at the same
  `created_at` as the meal bolus. NO `fat` / `protein` macros (FPU
  support is a Trio extension oref0 doesn't ship).
- **NO client-side dedupe**: no `id` UUID, no `pumpId`/`pumpType`/
  `pumpSerial` triple. Relies entirely on Nightscout's server-side
  `_id` and `created_at + eventType`-based dedupe.
- **devicestatus** carries `openaps + pump`, with a TOP-LEVEL
  `uploaderBattery` int (AAPS-style), NOT a nested `uploader`
  object (Loop / Trio-style). NO `configuration` subtree
  (AAPS-specific). NO `bolusIncrement` in `pump` (Trio-specific).
- **Determination JSON** uses CAPITAL keys (`IOB`, `COB`, `ISF`,
  `CR`, `TDD`, `predBGs.{IOB,COB,UAM,ZT}`) -- this is the canonical
  oref-wire convention oref0 originated and the descendants
  inherited. `received` (correctly spelled, lowercase) on `enacted`.
- **Profile** is the bare standard NS profile shape -- NO iOS-
  specific fields (`bundleIdentifier`, `deviceToken`,
  `isAPNSProduction`, `teamID`, `overridePresets`); those are Trio
  additions.

Cross-checked against upstream `openaps/oref0` source rather than
relying solely on the reference repo:
- `openaps/oref0:bin/ns-status.js` (devicestatus payload)
- `openaps/oref0:lib/bolus.js` (eventType assignment for Meal /
  Correction / SMB boluses)
- `openaps/oref0:examples/suggested.json` (Determination shape)
- `openaps/oref0:bin/oref0-ns-loop.sh` (carb upload flow)

#### `xdrip4ios`

The xDrip4iOS lens emits the **pure-CGM** wire format. xDrip4iOS is
a Nightscout uploader for Apple devices that reads Dexcom G6/G7 (via
direct Bluetooth) or Libre 2/3 (via a transmitter bridge like
MiaoMiao/Bubble/Atom). It is NOT a closed-loop system -- no
algorithm, no automated dosing, no `openaps` payload. The lens
exists to exercise the GlycemicGPT translator's "entries-only +
manual treatments" code paths that the closed-loop lenses don't
hit.

| Variable | Default | Purpose |
|---|---|---|
| `NS_XDRIP4IOS_TRANSMITTER` | `Dexcom G6` | Stamped into the entries `device` field. xDrip4iOS uses the actual transmitter name (per upstream `BgReading+Nightscout.swift` → `BgReading.deviceName`). Override to `"Dexcom G7"`, `"MiaoMiao"`, `"Bubble"`, `"Atom"`, etc. when stress-testing the translator's `detect_uploader` against varied transmitter strings. |

`NS_RANDOM_SEED` doesn't apply here -- xDrip4iOS has no
80/20 SMB-vs-manual split (no algorithm).

Real xDrip4iOS behaviors this lens models:

- **Identity**: `device` = transmitter name (NOT the app);
  `enteredBy: "xDrip4iOS"` literal on every treatment, per
  upstream `Source/Managers/Nightscout/NightscoutSyncManager.swift`
  which hardcodes `ConstantsHomeView.applicationName`.
- **Entries carry RAW SENSOR METADATA**: `filtered`, `unfiltered`,
  and a hardcoded `noise: 1`. The closed-loop lenses don't emit
  these -- they work from glucose values, not raw sensor signal.
  Distinctive xDrip / xDrip+ wire-format fingerprint.
- **Devicestatus is MINIMAL**: `device + uploader.{name:
  "transmitter", battery, batteryVoltage}` only. NO `openaps`,
  NO `loop`, NO `pump` subtree. The `uploader.battery` carries the
  TRANSMITTER battery (Dexcom voltage 3-4.5V, Libre %), not the
  phone battery.
- **No profile upload**: xDrip4iOS reads the user's NS profile to
  display targets / ISF / CR for follower-mode views, but does
  NOT post one. This emulator lens posts a baseline profile only
  if one doesn't already exist (so the test stack has a consistent
  state) and stamps `enteredBy: "openaps"` (the Care Portal
  sentinel) to honor the contract that xDrip4iOS doesn't author
  profiles.
- **Bolus eventType is just `"Bolus"`**: xDrip4iOS doesn't
  distinguish Meal Bolus / Correction Bolus / SMB on the wire --
  it has no algorithm, just a manual user-entry UI.
- **Carbs eventType is `"Carbs"`** (NOT `"Carb Correction"`):
  per upstream `treatment-classification.md`, xDrip4iOS's
  `TreatmentType.Carbs` maps to the simpler `"Carbs"` eventType.
- **Once-per-sim-day fingerstick BG Check**: real users
  calibrate Dexcom G6 / Libre 1 sensors with daily fingersticks;
  the lens fires a `"BG Check"` treatment in the morning window
  to exercise that path.
- **No SMBs / no algorithm-driven temp basals**: corrections come
  through as plain `"Bolus"` treatments. Temp Basals are not
  emitted at all (xDrip4iOS users get basal from their pump's own
  program, not from the uploader app).

Cross-checked against upstream `JohanDegraeve/xdripswift` source
files:
- `Source/Managers/Nightscout/NightscoutSyncManager.swift` (sync
  orchestration, devicestatus payload)
- `Source/Managers/Nightscout/BgReading+Nightscout.swift` (entry
  shape including `filtered` / `unfiltered` / `noise: 1`)
- `Source/Core Data/classes/TreatmentEntry+CoreDataClass.swift`
  (treatment model and upload code paths)

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
