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
| `xdrip_plus` | xDrip+ (Android, pure-CGM uploader) | Shipped | `mapping/xdrip-android/` + upstream `NightscoutFoundation/xDrip` |
| `librelink_up` | LibreLinkUp (Abbott cloud → NS bridge) | Shipped | `mapping/nightscout-librelink-up/` + upstream `timoschlueter/nightscout-librelink-up` |
| `share2ns` | share2nightscout-bridge (Dexcom Share cloud → NS) | Shipped | `mapping/share2nightscout-bridge/` + upstream `nightscout/share2nightscout-bridge` |
| `tconnectsync` | tconnectsync (Tandem t:connect cloud → NS) | Shipped | `mapping/tconnectsync/` + upstream `jwoglom/tconnectsync` |
| `manual` | Care Portal (Nightscout's built-in human-typed web UI) | Shipped | `mapping/cgm-remote-monitor/` + upstream `nightscout/cgm-remote-monitor` |

### Planned lenses (each its own PR)

| Lens | Platform | Reference doc |
|---|---|---|
| `iaps` | iAPS (Trio's predecessor) | `mapping/trio/nightscout-sync.md` |

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

#### `xdrip_plus`

The xDrip+ lens emits the **Android pure-CGM** wire format. xDrip+
(`NightscoutFoundation/xDrip`, Java/Kotlin) is the original Android
xDrip uploader and predates xDrip4iOS by ~5 years. It supports a
wider range of CGM data sources (Dexcom G4/G5/G6/G7, Libre 1/2/3,
LimiTTer, Bluetooth Wixel, MiaoMiao, Bubble, NS Follower). Like
xdrip4ios it is NOT a closed-loop system.

This lens is the SIBLING of `xdrip4ios`, but the wire format
diverges on every important field.

| Variable | Default | Purpose |
|---|---|---|
| `NS_XDRIP_PLUS_COLLECTION` | `DexcomG6` | The `dex_collection_method` value xDrip+ stamps inside the entries `device` field as `"xDrip-<method>"`. Override to `"DexcomG5"`, `"LimiTTer"`, `"BluetoothWixel"`, `"MiaoMiao"`, `"LibreReceiver"`, `"NSFollower"`, etc. (full enum in upstream `DexCollectionType.java`). |
| `NS_XDRIP_PLUS_PHONE_MODEL` | `Pixel7Pro` | The phone model xDrip+ stamps in the devicestatus `device` field as `"xDrip-<model>"` (real upstream uses `Build.MANUFACTURER + Build.MODEL`). Override to `"GooglePixel8"` / `"SamsungS23"` / `"OnePlus11"` / etc. |

**Top divergences from `xdrip4ios`:**

- **`enteredBy: "xdrip"`** (lowercase, no plus, no version), per
  upstream `Treatments.java`'s `XDRIP_TAG = "xdrip"` constant.
  xdrip4ios stamps `"xDrip4iOS"`.
- **`device: "xDrip-DexcomG6"`** (entries) and `"xDrip-Pixel7Pro"`
  (devicestatus) -- the `"xDrip-"` prefix is structural, NOT the
  bare transmitter name xdrip4ios uses.
- **Entries carry MORE metadata**: `delta` (BG-change rate),
  `rssi: 100` (hardcoded), `sysTime` (ISO timestamp). Plus the
  shared xDrip-family fields (`filtered`, `unfiltered`, `noise`).
- **Treatment vocabulary is RICHER**: `"Carb Correction"` (NOT
  `"Carbs"`), `"Meal Bolus"` / `"Correction Bolus"` (NOT flat
  `"Bolus"`), `"Sensor Stop"` event (xDrip+ extension). Every
  treatment carries a client-generated UUID.
- **Devicestatus**: minimal like xdrip4ios but the `device` field
  carries the phone model (`"xDrip-Pixel7Pro"`), not the
  transmitter name.

Cross-checked against upstream `NightscoutFoundation/xDrip` source
files:
- `app/src/main/java/com/eveningoutpost/dexdrip/utilitymodels/NightscoutUploader.java`
  (REST upload logic, payload builders for entries / treatments /
  devicestatus)
- `app/src/main/java/com/eveningoutpost/dexdrip/models/Treatments.java`
  (`XDRIP_TAG = "xdrip"` constant)
- `app/src/main/java/com/eveningoutpost/dexdrip/utils/DexCollectionType.java`
  (enum of CGM data sources used in the `device` field)
- `app/src/main/java/com/eveningoutpost/dexdrip/models/BgReading.java`
  (`noiseValue()` / `usedRaw()` / `ageAdjustedFiltered()` helpers)

#### `librelink_up`

The LibreLink Up lens emits the **Abbott cloud → Nightscout
bridge** wire format. LibreLinkUp
(`timoschlueter/nightscout-librelink-up`, Node.js / TypeScript) is
a server-side bridge -- typically a Docker container -- that polls
Abbott's LibreLinkUp web API on a 5-min schedule, fetches the
recent-most Libre 2/3 readings the Abbott cloud has received from
a paired follower account, and forwards them to Nightscout.

This is the simplest lens architecturally: **strictly entries-only**.
No closed-loop output, no raw sensor metadata, no devicestatus, no
treatments, no profile authorship. Per upstream
`src/nightscout/apiv1.ts`, the bridge implements only
`uploadEntries()` and `lastEntry()`.

| Variable | Default | Purpose |
|---|---|---|
| `NS_LIBRELINK_UP_DEVICE` | `nightscout-librelink-up` | The `device` field stamped on every entry. Per upstream `src/config.ts`'s `NIGHTSCOUT_DEVICE_NAME` default. Override to match a custom Docker deployment. |

**Top distinctions vs the previous CGM-only lenses (`xdrip4ios`, `xdrip_plus`):**

- **No raw sensor metadata** -- entries OMIT `filtered`,
  `unfiltered`, `noise`, `rssi`, `delta`, `sysTime`. Abbott's cloud
  API doesn't expose raw sensor signal; the bridge only sees
  Abbott's processed `ValueInMgPerDl` and a trend enum.
- **No `enteredBy` field** -- per upstream `Entry` interface in
  `src/nightscout/interface.ts`, LibreLinkUp doesn't set this.
  xDrip-family lenses always set it.
- **Trend enum is a SUBSET** -- only `SingleDown`, `FortyFiveDown`,
  `Flat`, `FortyFiveUp`, `SingleUp` (no `DoubleUp` / `DoubleDown`,
  per upstream `mapTrendArrow`). Abbott's cloud doesn't return
  Dexcom-style double arrows. This lens clamps the shared
  `direction_for()` helper's output to the LibreLinkUp subset.
- **Cloud-poll cadence** -- real LibreLinkUp polls Abbott every 5
  minutes via `node-cron`. Subject to Abbott outages, rate limits,
  and network latency. The emulator posts on the same 5-min
  cadence as the rest of the lenses; real LibreLinkUp would skip
  cycles when Abbott has no new data, but the emulator's shared
  physiology engine always produces a BG so this lens always has
  something to post.

**Translator-side note**: `detect_uploader` doesn't recognize
`"nightscout-librelink-up"` as a known uploader (no substring
match for `librelink` or `abbott`). Real LibreLinkUp deployments
hit this same gap -- entries get classified as `unknown` for the
uploader purposes. No functional impact since no code paths branch
on `uploader == "librelink_up"`. Documented for the future
translator improvement.

Cross-checked against upstream
`timoschlueter/nightscout-librelink-up` source files:
- `src/index.ts` (cron scheduler, polling loop)
- `src/config.ts` (env-var defaults including
  `NIGHTSCOUT_DEVICE_NAME`)
- `src/nightscout/apiv1.ts` (`uploadEntries` payload mapping)
- `src/nightscout/interface.ts` (Entry interface definition)
- `src/helpers/helpers.ts` (`mapTrendArrow` -- 5-value enum)

#### `share2ns`

The share2ns lens emits the **Dexcom Share cloud → Nightscout
bridge** wire format. share2nightscout-bridge
(`nightscout/share2nightscout-bridge`, Node.js) is the Dexcom
analogue of LibreLinkUp -- a server-side bridge that polls Dexcom's
Share servers (US: `share2.dexcom.com`, EU: `shareous1.dexcom.com`)
on a 2.5-min schedule and forwards readings to Nightscout.

| Variable | Default | Purpose |
|---|---|---|
| `NS_SHARE2NS_DEVICE` | `share2` | The `device` field stamped on every entry. Per upstream `index.js` which hardcodes `device: 'share2'` -- short, generic, device-agnostic. |

**Top divergences vs `librelink_up`:**

- **`device: "share2"`** literal (vs LibreLinkUp's
  `"nightscout-librelink-up"`).
- **Full 9-value Dexcom trend enum**: every entry POST carries
  BOTH `direction` (string) AND a numeric `trend` field
  (`DoubleUp=1, SingleUp=2, FortyFiveUp=3, Flat=4,
  FortyFiveDown=5, SingleDown=6, DoubleDown=7, NOT COMPUTABLE=8,
  RATE OUT OF RANGE=9`). LibreLinkUp omits `trend` entirely AND
  only supports 5 directions.
- **One-time devicestatus on startup**: posts
  `{uploaderBattery: false}` ONCE to suppress the Nightscout
  uploader-battery indicator, then never posts devicestatus
  again. LibreLinkUp doesn't post devicestatus at all.

Like LibreLinkUp, share2ns is strictly entries-focused with no
treatments / profile authoring. Cloud bridges are one-way
ingestion pipes.

**Translator-side note**: `detect_uploader` doesn't recognize
`"share2"` as a known uploader (no substring match for `dexcom`
or `share`). Real share2ns deployments hit this same gap. No
functional impact -- no code paths branch on
`uploader == "share2ns"`. Documented for the future translator
improvement: `device == "share2"` could be a recognition signal.

Cross-checked against upstream `nightscout/share2nightscout-bridge`:
- `index.js` (the entire bridge is a single JS file -- entry
  mapping at lines 226-230, devicestatus at lines 265-273,
  `matchTrend()` at lines 56-66)

#### `tconnectsync`

The tconnectsync lens emits the **Tandem t:connect cloud →
Nightscout bridge** wire format. tconnectsync (`jwoglom/tconnectsync`,
Python, MIT) is a server-side bridge that polls Tandem's t:connect
cloud (the cloud that t:slim X2 / Mobi pumps batch-upload to) and
forwards pump events to Nightscout. Architecturally distinct from
every prior cloud-bridge lens: where LibreLinkUp / share2ns forward
**CGM-only** data from a sensor cloud, tconnectsync forwards
**pump-side therapy data** -- boluses, basals, site changes,
battery state -- alongside CGM (Dexcom paired with the pump).

| Variable | Default | Purpose |
|---|---|---|
| `NS_TCONNECTSYNC_DEVICE` | `Pump (tconnectsync)` | The `device` / `enteredBy` string stamped on every record. Per upstream `tconnectsync/parser/nightscout.py`'s `ENTERED_BY` constant. The local RAG document claims `"tconnectsync"` (no parens) -- per the repo memory rule, upstream wins; the RAG is stale. |

**Top divergences vs every prior lens:**

- **Identity is `"Pump (tconnectsync)"`** -- literal string with
  parentheses + space. Stamped on every treatment, entry, AND
  devicestatus record (no other lens uses this exact form).
- **`pump_event_id` field on every record**: monotonic pump
  sequence number (e.g., `"100123"`). Used by tconnectsync for
  client-side dedupe queries against NS. AAPS uses
  `pumpId/pumpType/pumpSerial`; Trio uses `id` (UUID); oref0 has
  no client dedupe; tconnectsync has its own.
- **All boluses are `"Combo Bolus"`**: meal, correction, extended,
  override, declined-correction -- ALL map to a single eventType
  with the distinction stuffed into the `notes` field (`"Meal
  Bolus"`, `"Correction Bolus"`, ...). Carbs are bundled into the
  same record (no separate `Carb Correction`). Hard divergence
  from every other lens.
- **Temp Basal carries a `reason` field** describing Control-IQ's
  rationale: `"Control-IQ"` (algorithm-controlled, no specific
  intent), `"Helping with Trend"` (BG dropping), `"Correcting
  High"`. Per upstream `process_basal.py`'s `changetype`-bitmask
  reason extraction. AAPS / Trio temp basals have no comparable
  field.
- **Entries OMIT `direction`**: t:connect's CGM API doesn't expose
  the trend arrow. Real divergence -- LibreLinkUp / share2ns /
  xDrip-family all include direction; tconnectsync cannot.
- **Devicestatus is MINIMAL `pump.battery` only**: voltage (volts,
  not millivolts) + percent + a human-readable string like
  `"85%"`. NO `openaps` / `loop` / `uploader` subtrees. NO
  reservoir level (real upstream gap -- t:connect API doesn't
  expose it).
- **Profile uploads a Tandem-pump schedule**: full basal / ICR /
  ISF / target schedule. Control-IQ default target is a NARROW
  110/110 mg/dL band (single-value, not a wide range). AAPS / Trio
  use a wider target_low/target_high split; this narrow band is a
  Tandem-specific signal.
- **Site Change for cartridge / cannula / tubing fills**: per
  upstream `process_cartridge.py`, all three fill types map to
  eventType `"Site Change"` with a `notes` field shaped
  `"Cartridge Filled (<n>u filled)"` (volume in units in
  parentheses) -- our reservoir-refill trigger emits the same
  format with the actual reservoir volume so downstream
  volume-extraction regex paths get exercised.

**Real-world latency**: t:connect cloud is **60-90 minutes behind
the pump** because Tandem batches uploads. Our emulator posts at
5-min sim cadence (matching the rest of the emulator's tick rate)
-- documented divergence; modeling true 60-90 min batched-upload
latency would require buffering and is orthogonal to NS wire-format
coverage.

**Translator-side note**: `detect_uploader` doesn't recognize
`"Pump (tconnectsync)"` as a known uploader (no substring match for
`tandem` or `tconnect`). Real tconnectsync deployments hit this
same gap. No functional impact -- no code paths branch on
`uploader == "tconnectsync"`. Documented for the future translator
improvement: `enteredBy == "Pump (tconnectsync)"` could be a
recognition signal.

Cross-checked against upstream `jwoglom/tconnectsync`:
- `tconnectsync/parser/nightscout.py` (`ENTERED_BY` constant,
  `NightscoutEntry` builders for bolus / basal / devicestatus /
  entry / profile)
- `tconnectsync/nightscout.py` (NS API v1 + SHA-1 auth)
- `tconnectsync/sync/tandemsource/process_bolus.py` (Combo Bolus
  + carbs bundling + notes)
- `tconnectsync/sync/tandemsource/process_basal.py` (Temp Basal +
  reason from `changetype` bitmask)
- `tconnectsync/sync/tandemsource/process_cartridge.py` (Site
  Change for cartridge / cannula / tubing fills)
- `tconnectsync/sync/tandemsource/process_device_status.py`
  (`pump.battery` shape: voltage + percent + status)
- `tconnectsync/sync/tandemsource/process_cgm_reading.py` (entry
  shape: no `direction`)
- `tconnectsync/sync/tandemsource/update_profiles.py` (profile
  schedule shape with narrow Control-IQ target band)

#### `manual`

The manual lens emits the **Care Portal** wire format -- Nightscout's
built-in web UI in `nightscout/cgm-remote-monitor` for users to type
entries / treatments directly into NS. Care Portal is a HUMAN AT A
KEYBOARD, not a connected device or a cloud bridge -- so the lens is
the most architecturally distinct of the 11 shipped lenses.

| Variable | Default | Purpose |
|---|---|---|
| `NS_MANUAL_ENTERED_BY` | `jane` | The user's typed name. Per upstream `lib/client/careportal.js:242` which presets `enteredBy` to the JWT subject or `localStorage.get('enteredBy')`. Set to empty string (`""`) to model a Care Portal POST without an `enteredBy` field, which is also a real upstream pattern. |

**Top divergences vs every prior lens:**

- **Identity is a username, not a machine ID**: `enteredBy` is the
  user's typed name (e.g. `"jane"`) -- NOT a fixed machine literal
  like `"loop"` / `"AndroidAPS"` / `"xDrip4iOS"` / `"Pump
  (tconnectsync)"`. Per upstream `lib/client/careportal.js`.
- **`device` is empty**: humans aren't devices. Every prior lens
  stamps a `device` field (the lens-name); manual sets it to `""`.
- **No periodic upload**: humans don't post on a 5-min cadence.
  Care Portal entries are sparse and unpredictable. Our emulator
  throttles entries to a min interval (default 30 sim-min for
  fingerstick BG -- denser than a real Care Portal user but useful
  for short-window dashboard testing; ~1 Note per sim-day).
- **No devicestatus, no profile authoring, no temp basals**: Care
  Portal doesn't post any of these. The Lens-contract methods for
  these are no-ops. The NS profile editor is a separate UI (`/profile/`)
  with its own POST path, NOT Care Portal.
- **Entries are `mbg` (manual blood glucose), not `sgv` (sensor
  glucose value)**: when a user types a fingerstick BG into Care
  Portal it goes in as `type: "mbg"` -- no `direction` (the meter
  doesn't report trend), no raw sensor metadata. This distinguishes
  Care Portal entries from every other lens' `sgv` posts.
- **Multi-eventType vocabulary**: Care Portal exposes 20+ eventTypes
  (BG Check, Meal Bolus, Snack Bolus, Carb Correction, Correction
  Bolus, Combo Bolus, Note, Question, Announcement, Exercise, Site
  Change, Sensor Start / Change / Stop, Pump Battery Change,
  Insulin Cartridge Change, Profile Switch, Temporary Target, ...).
  We model the operationally meaningful subset that real T1D users
  post most often: BG Check, Meal Bolus, Correction Bolus, Site
  Change, Note. Per upstream `lib/plugins/careportal.js`'s
  `getEventTypes()`.
- **BG Check double-post (emulator simplification)**: the lens
  posts BOTH an `mbg` entry AND a `BG Check` treatment at the same
  timestamp on each fingerstick. **Upstream caveat**: Care Portal's
  web UI does NOT actually double-post -- `lib/client/careportal.js`
  submits a single `/api/v1/treatments.json` POST per form submit.
  Real `mbg` entries on production NS instances come from xDrip-
  style direct uploaders / watchface apps / scripts hitting the
  entries endpoint, NOT Care Portal. We emit both because the
  `BG Check` treatment's translator routing
  (`fingerstick_bg_check`) is intentionally dropped, so without
  the `mbg` entry the GlycemicGPT dashboard would render no BG
  data for this lens at all. Both shapes are valid NS wire
  formats; this is a documented divergence kept for dashboard
  test density.

**Translator-side note**: `detect_uploader` doesn't currently return
`"care_portal"` -- empty `enteredBy` + empty `device` falls through
to `"unknown"`. Real Care Portal users hit this same gap. No
functional impact since no code paths branch on
`uploader == "care_portal"`. Documented for future translator
improvement: `enteredBy` matching a free-text human name (no machine
URI / namespace / known-app-name) could be a recognition signal.

Cross-checked against upstream `nightscout/cgm-remote-monitor`:
- `lib/client/careportal.js` (form submission, `enteredBy` default
  to JWT subject or localStorage, field-omission rules)
- `lib/plugins/careportal.js` (`getEventTypes()` -- 20-strong
  eventType vocabulary + per-type field flags)
- `lib/server/treatments.js` (server-side ingestion -- `replaceOne`
  upsert keyed on `created_at`; the composite `eventType + duration
  + created_at` index is for query speed, not dedupe)

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
