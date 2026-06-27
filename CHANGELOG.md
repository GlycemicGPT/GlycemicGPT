# Changelog

## 2026-06-27

### 📱 Mobile

#### 💥 Breaking Changes

- fix(api): harden glucose ingestion for mmol/L unit safety [@dxwood01](https://github.com/dxwood01) ([#806](https://github.com/GlycemicGPT/GlycemicGPT/pull/806))

#### ✨ New Features

- feat(mobile): make the Home "Log a meal" FAB draggable [@jlengelbrecht](https://github.com/jlengelbrecht) ([#826](https://github.com/GlycemicGPT/GlycemicGPT/pull/826))
- feat: per-user Meal Intelligence setting replacing the env-var gate [@jlengelbrecht](https://github.com/jlengelbrecht) ([#823](https://github.com/GlycemicGPT/GlycemicGPT/pull/823))
- feat: seed glucose display unit from region and Nightscout (overridable) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#816](https://github.com/GlycemicGPT/GlycemicGPT/pull/816))
- feat(mobile): render Wear OS glucose in the user's unit (mg/dL or mmol/L) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#812](https://github.com/GlycemicGPT/GlycemicGPT/pull/812))
- feat(mobile): render phone glucose display in the user's unit (mg/dL or mmol/L) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#807](https://github.com/GlycemicGPT/GlycemicGPT/pull/807))

#### 🐛 Bug Fixes

- fix: classify CareLink import errors as transport vs unexpected response [@gitcommit90](https://github.com/gitcommit90) ([#814](https://github.com/GlycemicGPT/GlycemicGPT/pull/814))

#### 📝 Other Changes

- test: verify cross-surface glucose-unit consistency and document units [@jlengelbrecht](https://github.com/jlengelbrecht) ([#818](https://github.com/GlycemicGPT/GlycemicGPT/pull/818))
- chore: sync release 0.10.0 from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#800](https://github.com/GlycemicGPT/GlycemicGPT/pull/800))

### 🌐 Web

#### 💥 Breaking Changes

- fix: support browser selection in connect helper [@sanmaxdev](https://github.com/sanmaxdev) ([#819](https://github.com/GlycemicGPT/GlycemicGPT/pull/819))
- feat:(GLY-57) upgrade tailwind 4 [@DanielDanielsson](https://github.com/DanielDanielsson) ([#790](https://github.com/GlycemicGPT/GlycemicGPT/pull/790))

#### ✨ New Features

- feat: render glucose alerts and caregiver views in the user's unit [@jlengelbrecht](https://github.com/jlengelbrecht) ([#804](https://github.com/GlycemicGPT/GlycemicGPT/pull/804))
- feat(web): mmol/L glucose unit toggle, display conversion, and input forms [@jlengelbrecht](https://github.com/jlengelbrecht) ([#802](https://github.com/GlycemicGPT/GlycemicGPT/pull/802))

### 📡 API

#### 💥 Breaking Changes

- feat(api): add glucose unit preference foundation [@DanielDanielsson](https://github.com/DanielDanielsson) ([#785](https://github.com/GlycemicGPT/GlycemicGPT/pull/785))

#### ✨ New Features

- feat(benchmarks): LLM benchmarking harness for BYOAI model safety/quality [@seitzbg](https://github.com/seitzbg) ([#828](https://github.com/GlycemicGPT/GlycemicGPT/pull/828))
- feat(api): verify AI-spoken glucose figures against the user's readings [@jlengelbrecht](https://github.com/jlengelbrecht) ([#805](https://github.com/GlycemicGPT/GlycemicGPT/pull/805))
- feat(api): render AI text and notifications in the user's glucose unit [@jlengelbrecht](https://github.com/jlengelbrecht) ([#803](https://github.com/GlycemicGPT/GlycemicGPT/pull/803))

#### 🐛 Bug Fixes

- fix(safety): block verb-independent specific insulin doses [@seitzbg](https://github.com/seitzbg) ([#829](https://github.com/GlycemicGPT/GlycemicGPT/pull/829))
- fix(food-records): return 404 when a record is deleted mid common-food promotion [@jlengelbrecht](https://github.com/jlengelbrecht) ([#825](https://github.com/GlycemicGPT/GlycemicGPT/pull/825))
- fix(medtronic-connect): drop ambiguous mmol/L follower glucose as a gap [@jlengelbrecht](https://github.com/jlengelbrecht) ([#821](https://github.com/GlycemicGPT/GlycemicGPT/pull/821))

### 🏗️ Infrastructure

#### 📝 Other Changes

- chore: sync changelog update from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#799](https://github.com/GlycemicGPT/GlycemicGPT/pull/799))

### 📚 Documentation

- docs(benchmarking): user + developer benchmarking guides [@seitzbg](https://github.com/seitzbg) ([#830](https://github.com/GlycemicGPT/GlycemicGPT/pull/830))

<!-- changelog-cutoff:2026-06-27T05:46:30Z -->


## 2026-06-20

### 📱 Mobile

#### ✨ New Features

- feat: web + mobile meal comorbidity nutrition (saturated fat, sugars, sodium) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#795](https://github.com/GlycemicGPT/GlycemicGPT/pull/795))
- feat: surface glucose-relevant meal nutrition with never-dose guardrails [@jlengelbrecht](https://github.com/jlengelbrecht) ([#791](https://github.com/GlycemicGPT/GlycemicGPT/pull/791))
- feat: meal-vision safety-language hardening [@jlengelbrecht](https://github.com/jlengelbrecht) ([#753](https://github.com/GlycemicGPT/GlycemicGPT/pull/753))
- feat: Milestone H — empirical confidence, identity gating & auditability (H1–H3) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#747](https://github.com/GlycemicGPT/GlycemicGPT/pull/747))
- feat(mobile): meal capture → estimate → correct → save (Meal Intelligence) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#738](https://github.com/GlycemicGPT/GlycemicGPT/pull/738))

#### 📝 Other Changes

- ci(android): run instrumented tests on an emulator in CI [@jlengelbrecht](https://github.com/jlengelbrecht) ([#786](https://github.com/GlycemicGPT/GlycemicGPT/pull/786))
- test(meal): end-to-end coverage for the meal-logging core loop and failure modes [@jlengelbrecht](https://github.com/jlengelbrecht) ([#783](https://github.com/GlycemicGPT/GlycemicGPT/pull/783))
- chore: sync release 0.9.0 from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#718](https://github.com/GlycemicGPT/GlycemicGPT/pull/718))

### 🌐 Web

#### ✨ New Features

- feat: web meal estimate provenance panel (how this was estimated) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#794](https://github.com/GlycemicGPT/GlycemicGPT/pull/794))
- feat: web common-foods management and save/link from a meal [@jlengelbrecht](https://github.com/jlengelbrecht) ([#793](https://github.com/GlycemicGPT/GlycemicGPT/pull/793))
- feat: web meal carb correction and food-identity confirmation [@jlengelbrecht](https://github.com/jlengelbrecht) ([#792](https://github.com/GlycemicGPT/GlycemicGPT/pull/792))
- feat: web meal management view (list, detail, delete, photo upload + serving) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#789](https://github.com/GlycemicGPT/GlycemicGPT/pull/789))
- feat(api): surface long-acting basal injections in TDD, AI context, and insulin views [@jlengelbrecht](https://github.com/jlengelbrecht) ([#744](https://github.com/GlycemicGPT/GlycemicGPT/pull/744))
- feat(api): add per-connection Glooko cgm_sync_enabled toggle (doses-only mode) [@chris-clem](https://github.com/chris-clem) ([#733](https://github.com/GlycemicGPT/GlycemicGPT/pull/733))

#### 🐛 Bug Fixes

- fix(deps): patch 18 OSV-flagged transitive CVEs across api/web/sidecar [@jlengelbrecht](https://github.com/jlengelbrecht) ([#750](https://github.com/GlycemicGPT/GlycemicGPT/pull/750))

### 📡 API

#### ✨ New Features

- feat(api): gate local AI vision models on a measured carb-estimation bar [@jlengelbrecht](https://github.com/jlengelbrecht) ([#788](https://github.com/GlycemicGPT/GlycemicGPT/pull/788))
- feat(api): ground branded restaurant items against published chain nutrition [@jlengelbrecht](https://github.com/jlengelbrecht) ([#787](https://github.com/GlycemicGPT/GlycemicGPT/pull/787))
- feat(api): verify AI-cited meal carb figures against logged meals [@jlengelbrecht](https://github.com/jlengelbrecht) ([#765](https://github.com/GlycemicGPT/GlycemicGPT/pull/765))
- feat(api): ground meal-photo carb estimates against history + USDA/OFF [@jlengelbrecht](https://github.com/jlengelbrecht) ([#746](https://github.com/GlycemicGPT/GlycemicGPT/pull/746))
- feat(api): surface logged meals in chat and daily brief [@jlengelbrecht](https://github.com/jlengelbrecht) ([#745](https://github.com/GlycemicGPT/GlycemicGPT/pull/745))
- feat(api): auto-generate daily briefs on a schedule [@chris-clem](https://github.com/chris-clem) ([#743](https://github.com/GlycemicGPT/GlycemicGPT/pull/743))
- feat(api): record long-acting (basal) pen injections from Glooko [@chris-clem](https://github.com/chris-clem) ([#740](https://github.com/GlycemicGPT/GlycemicGPT/pull/740))
- feat(api): meal correction loop + common foods [@jlengelbrecht](https://github.com/jlengelbrecht) ([#737](https://github.com/GlycemicGPT/GlycemicGPT/pull/737))
- feat(api): food_records model + photo carb-estimation pipeline [@jlengelbrecht](https://github.com/jlengelbrecht) ([#736](https://github.com/GlycemicGPT/GlycemicGPT/pull/736))
- feat(api): ingest smart-pen insulin doses (NovoPen 6 / Echo Plus) via Glooko [@chris-clem](https://github.com/chris-clem) ([#726](https://github.com/GlycemicGPT/GlycemicGPT/pull/726))

#### 🐛 Bug Fixes

- fix(api): deterministic, self-excluding own-history meal recall [@jlengelbrecht](https://github.com/jlengelbrecht) ([#784](https://github.com/GlycemicGPT/GlycemicGPT/pull/784))
- fix(api): harden meal-identity clustering against verbose descriptions [@jlengelbrecht](https://github.com/jlengelbrecht) ([#766](https://github.com/GlycemicGPT/GlycemicGPT/pull/766))
- fix(api): make tzlocal an explicit dependency [@jlengelbrecht](https://github.com/jlengelbrecht) ([#752](https://github.com/GlycemicGPT/GlycemicGPT/pull/752))
- fix(api): show large pen doses (60U bound) and dedupe Glooko doses across sources [@jlengelbrecht](https://github.com/jlengelbrecht) ([#731](https://github.com/GlycemicGPT/GlycemicGPT/pull/731))
- fix(api): count non-pump insulin doses past the pump IoB anchor [@jlengelbrecht](https://github.com/jlengelbrecht) ([#730](https://github.com/GlycemicGPT/GlycemicGPT/pull/730))
- fix(api): harden Glooko host validation, 421 posture, and dose ingestion bounds [@jlengelbrecht](https://github.com/jlengelbrecht) ([#729](https://github.com/GlycemicGPT/GlycemicGPT/pull/729))
- fix(api): follow Glooko EU sub-cluster redirect when resolving the API host [@chris-clem](https://github.com/chris-clem) ([#725](https://github.com/GlycemicGPT/GlycemicGPT/pull/725))
- fix(api): fail closed on Redis outage for single-use token consumption [@jlengelbrecht](https://github.com/jlengelbrecht) ([#720](https://github.com/GlycemicGPT/GlycemicGPT/pull/720))

#### 📝 Other Changes

- test(api): assert a single Alembic head (CI guard) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#739](https://github.com/GlycemicGPT/GlycemicGPT/pull/739))

### 🤖 Sidecar

#### 💥 Breaking Changes

- fix(sidecar): require SIDECAR_API_KEY at startup, fail closed on missing auth [@jlengelbrecht](https://github.com/jlengelbrecht) ([#719](https://github.com/GlycemicGPT/GlycemicGPT/pull/719))

#### ✨ New Features

- feat(sidecar): per-provider vision support + carb-estimation eval harness (Meal Intelligence) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#735](https://github.com/GlycemicGPT/GlycemicGPT/pull/735))

#### 🐛 Bug Fixes

- fix(sidecar): route codex (ChatGPT subscription) chat through codex exec --json [@jlengelbrecht](https://github.com/jlengelbrecht) ([#749](https://github.com/GlycemicGPT/GlycemicGPT/pull/749))
- fix(sidecar): install ca-certificates so codex (ChatGPT subscription) works [@jlengelbrecht](https://github.com/jlengelbrecht) ([#748](https://github.com/GlycemicGPT/GlycemicGPT/pull/748))

### 🔒 Security

#### 📝 Other Changes

- ci(security): suppress false-positive AES-ECB SAST finding in vendored SAKE crypto (#695/#696) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#751](https://github.com/GlycemicGPT/GlycemicGPT/pull/751))

### 🏗️ Infrastructure

#### 💥 Breaking Changes

- chore(ci): stop auto-labeler flagging templated PRs as breaking changes [@jlengelbrecht](https://github.com/jlengelbrecht) ([#732](https://github.com/GlycemicGPT/GlycemicGPT/pull/732))

#### ✨ New Features

- feat(evals): variance-aware vision-carb eval harness + adversarial food set [@jlengelbrecht](https://github.com/jlengelbrecht) ([#754](https://github.com/GlycemicGPT/GlycemicGPT/pull/754))

#### 🐛 Bug Fixes

- fix(infra): loopback-bind dev Postgres/Redis, add Redis auth, fix k8s pgvector [@jlengelbrecht](https://github.com/jlengelbrecht) ([#721](https://github.com/GlycemicGPT/GlycemicGPT/pull/721))

#### 📝 Other Changes

- chore: sync changelog update from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#717](https://github.com/GlycemicGPT/GlycemicGPT/pull/717))

<!-- changelog-cutoff:2026-06-20T05:41:54Z -->


## 2026-06-10

### 📱 Mobile

#### ✨ New Features

- feat(mobile): Nightscout cloud-source plugin [@jlengelbrecht](https://github.com/jlengelbrecht) ([#712](https://github.com/GlycemicGPT/GlycemicGPT/pull/712))
- feat(medtronic): advertise-and-wait pairing UX + driver kill-switch [@jlengelbrecht](https://github.com/jlengelbrecht) ([#704](https://github.com/GlycemicGPT/GlycemicGPT/pull/704))
- feat(medtronic): render pump connection notes in settings card [@jlengelbrecht](https://github.com/jlengelbrecht) ([#703](https://github.com/GlycemicGPT/GlycemicGPT/pull/703))
- feat(medtronic): poll/persist/push pipeline integration with single-flight reads [@jlengelbrecht](https://github.com/jlengelbrecht) ([#702](https://github.com/GlycemicGPT/GlycemicGPT/pull/702))
- feat(medtronic): on-device BluetoothGatt-client read transport [@jlengelbrecht](https://github.com/jlengelbrecht) ([#701](https://github.com/GlycemicGPT/GlycemicGPT/pull/701))
- feat(medtronic): capability delegates + DevicePlugin + Hilt/:app wiring [@jlengelbrecht](https://github.com/jlengelbrecht) ([#700](https://github.com/GlycemicGPT/GlycemicGPT/pull/700))
- feat(medtronic): IDD status + history/RACP read-only readers [@jlengelbrecht](https://github.com/jlengelbrecht) ([#699](https://github.com/GlycemicGPT/GlycemicGPT/pull/699))
- feat(medtronic): session-read framework + CGM/SG, Device Info, and Battery readers [@jlengelbrecht](https://github.com/jlengelbrecht) ([#698](https://github.com/GlycemicGPT/GlycemicGPT/pull/698))
- feat(medtronic): peripheral-mode BLE connection manager with SAKE session and reconnect [@jlengelbrecht](https://github.com/jlengelbrecht) ([#697](https://github.com/GlycemicGPT/GlycemicGPT/pull/697))
- feat(medtronic): read-only BLE driver module with SAKE session and protocol constants [@jlengelbrecht](https://github.com/jlengelbrecht) ([#694](https://github.com/GlycemicGPT/GlycemicGPT/pull/694))
- feat(mobile): wire Sentry crash/error reporting into the Android app [@jlengelbrecht](https://github.com/jlengelbrecht) ([#693](https://github.com/GlycemicGPT/GlycemicGPT/pull/693))

#### 🐛 Bug Fixes

- fix(tandem): remove cloud-upload feature [@jlengelbrecht](https://github.com/jlengelbrecht) ([#668](https://github.com/GlycemicGPT/GlycemicGPT/pull/668))

#### 📝 Other Changes

- chore: sync release 0.8.2 from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#666](https://github.com/GlycemicGPT/GlycemicGPT/pull/666))

### 🌐 Web

#### ✨ New Features

- feat: cross-source CGM dedupe + primary-source picker (Story 43.10) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#711](https://github.com/GlycemicGPT/GlycemicGPT/pull/711))
- feat(integrations): make Omnipod/Glooko EU region a first-class option [@jlengelbrecht](https://github.com/jlengelbrecht) ([#690](https://github.com/GlycemicGPT/GlycemicGPT/pull/690))
- feat(integrations): Omnipod cloud sync via Glooko [@jlengelbrecht](https://github.com/jlengelbrecht) ([#689](https://github.com/GlycemicGPT/GlycemicGPT/pull/689))
- feat(integrations): Medtronic CareLink Connect autonomous cloud sync [@jlengelbrecht](https://github.com/jlengelbrecht) ([#686](https://github.com/GlycemicGPT/GlycemicGPT/pull/686))
- feat(web): server-side-only Sentry error monitoring (disabled by default) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#677](https://github.com/GlycemicGPT/GlycemicGPT/pull/677))
- feat: Medtronic CareLink manual historical import [@jlengelbrecht](https://github.com/jlengelbrecht) ([#671](https://github.com/GlycemicGPT/GlycemicGPT/pull/671))
- feat(tandem): Cloud Sync card with per-user sync, availability, and manual import [@jlengelbrecht](https://github.com/jlengelbrecht) ([#669](https://github.com/GlycemicGPT/GlycemicGPT/pull/669))
- feat(web): forecast picker + dotted-line overlay (43.12 PR 4) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#636](https://github.com/GlycemicGPT/GlycemicGPT/pull/636))

#### 🐛 Bug Fixes

- fix(integrations): refresh Glooko card status after a failed sync/import [@jlengelbrecht](https://github.com/jlengelbrecht) ([#691](https://github.com/GlycemicGPT/GlycemicGPT/pull/691))
- fix(web): stop the glucose SSE proxy from leaking aborts into Sentry [@jlengelbrecht](https://github.com/jlengelbrecht) ([#688](https://github.com/GlycemicGPT/GlycemicGPT/pull/688))

#### 📝 Other Changes

- chore(deps): clear Dependabot dev/build advisories before release [@jlengelbrecht](https://github.com/jlengelbrecht) ([#714](https://github.com/GlycemicGPT/GlycemicGPT/pull/714))
- chore(deps): update dependency postcss to v8.5.15 [@glycemicgpt-renovate](https://github.com/glycemicgpt-renovate) ([#607](https://github.com/GlycemicGPT/GlycemicGPT/pull/607))
- chore(deps): update dependency recharts to v3.8.1 [@glycemicgpt-renovate](https://github.com/glycemicgpt-renovate) ([#559](https://github.com/GlycemicGPT/GlycemicGPT/pull/559))

### 📡 API

#### ✨ New Features

- feat(api): cross-source pump-event dedupe via content hash (Story 43.11) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#710](https://github.com/GlycemicGPT/GlycemicGPT/pull/710))
- feat(api): add Sentry error monitoring (disabled by default) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#672](https://github.com/GlycemicGPT/GlycemicGPT/pull/672))

#### 🐛 Bug Fixes

- fix(api): bump pyjwt to 2.13.0 to clear PYSEC-2026 advisories [@jlengelbrecht](https://github.com/jlengelbrecht) ([#705](https://github.com/GlycemicGPT/GlycemicGPT/pull/705))
- fix(caregiver): resolve 500 on invitation creation [@jlengelbrecht](https://github.com/jlengelbrecht) ([#685](https://github.com/GlycemicGPT/GlycemicGPT/pull/685))
- fix(deps): patch starlette PYSEC-2026-161 and harden the ecdsa OSV exception [@jlengelbrecht](https://github.com/jlengelbrecht) ([#674](https://github.com/GlycemicGPT/GlycemicGPT/pull/674))

#### 📝 Other Changes

- chore(api): harden Sentry URL scrubbing and refresh privacy status [@jlengelbrecht](https://github.com/jlengelbrecht) ([#675](https://github.com/GlycemicGPT/GlycemicGPT/pull/675))
- Fix Tandem cloud upload silent-success + scheduler diagnostics [@jlengelbrecht](https://github.com/jlengelbrecht) ([#667](https://github.com/GlycemicGPT/GlycemicGPT/pull/667))
- chore(deps): lock file maintenance [@glycemicgpt-renovate](https://github.com/glycemicgpt-renovate) ([#557](https://github.com/GlycemicGPT/GlycemicGPT/pull/557))

### 🤖 Sidecar

#### ✨ New Features

- feat(sidecar): add Sentry error monitoring (disabled by default) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#676](https://github.com/GlycemicGPT/GlycemicGPT/pull/676))

#### 📝 Other Changes

- chore(deps): update dependency express to v4.22.2 [@glycemicgpt-renovate](https://github.com/glycemicgpt-renovate) ([#653](https://github.com/GlycemicGPT/GlycemicGPT/pull/653))

### 🏗️ Infrastructure

#### ✨ New Features

- feat(medtronic): offline peripheral-BLE + SAKE handshake de-risk spike [@jlengelbrecht](https://github.com/jlengelbrecht) ([#692](https://github.com/GlycemicGPT/GlycemicGPT/pull/692))
- feat(k8s): wire Sentry DSN env passthrough for api/sidecar/web [@jlengelbrecht](https://github.com/jlengelbrecht) ([#678](https://github.com/GlycemicGPT/GlycemicGPT/pull/678))

#### 🐛 Bug Fixes

- fix(ci): green develop after Medtronic Connect merge (helper-src context + x/sys CVE) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#687](https://github.com/GlycemicGPT/GlycemicGPT/pull/687))

#### 📝 Other Changes

- chore: sync changelog update from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#665](https://github.com/GlycemicGPT/GlycemicGPT/pull/665))

### 📚 Documentation

- docs(readme): add Medtronic 700-series + web dashboard demo + trim badges [@jlengelbrecht](https://github.com/jlengelbrecht) ([#709](https://github.com/GlycemicGPT/GlycemicGPT/pull/709))
- docs(medtronic): OpenMinimed attribution, GPL-3.0 licensing, and BLE pairing guide [@jlengelbrecht](https://github.com/jlengelbrecht) ([#706](https://github.com/GlycemicGPT/GlycemicGPT/pull/706))
- docs(roadmap): name the shared memory layer under AI Engine 2.0 [@jlengelbrecht](https://github.com/jlengelbrecht) ([#684](https://github.com/GlycemicGPT/GlycemicGPT/pull/684))
- docs: add Sentry for Good sponsor and privacy posture [@jlengelbrecht](https://github.com/jlengelbrecht) ([#670](https://github.com/GlycemicGPT/GlycemicGPT/pull/670))

<!-- changelog-cutoff:2026-06-10T18:20:27Z -->


## 2026-05-18

### 📱 Mobile

#### 📝 Other Changes

- chore: sync release 0.8.1 from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#659](https://github.com/GlycemicGPT/GlycemicGPT/pull/659))

### 🌐 Web

#### 📝 Other Changes

- chore(web): bump ws to 8.20.1 to patch GHSA-58qx-3vcg-4xpx [@jlengelbrecht](https://github.com/jlengelbrecht) ([#662](https://github.com/GlycemicGPT/GlycemicGPT/pull/662))

### 🏗️ Infrastructure

#### 🐛 Bug Fixes

- fix(ci): verify-release-tags case-sensitivity + dev-prerelease + JS pull URLs [@jlengelbrecht](https://github.com/jlengelbrecht) ([#660](https://github.com/GlycemicGPT/GlycemicGPT/pull/660))

#### 📝 Other Changes

- chore: sync changelog update from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#658](https://github.com/GlycemicGPT/GlycemicGPT/pull/658))

<!-- changelog-cutoff:2026-05-18T23:40:47Z -->


## 2026-05-18

### 📱 Mobile

#### 📝 Other Changes

- chore: sync release 0.8.0 from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#651](https://github.com/GlycemicGPT/GlycemicGPT/pull/651))

### 🌐 Web

#### 🐛 Bug Fixes

- fix(web): self-host Inter font + verify release container tags [@jlengelbrecht](https://github.com/jlengelbrecht) ([#654](https://github.com/GlycemicGPT/GlycemicGPT/pull/654))

### 🏗️ Infrastructure

#### 📝 Other Changes

- chore: sync changelog update from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#650](https://github.com/GlycemicGPT/GlycemicGPT/pull/650))

<!-- changelog-cutoff:2026-05-18T19:38:04Z -->


## 2026-05-18

### 📱 Mobile

#### 📝 Other Changes

- chore: sync release 0.7.2 from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#632](https://github.com/GlycemicGPT/GlycemicGPT/pull/632))

### 🌐 Web

#### ✨ New Features

- feat(api, web): vendor-agnostic data-flow disclosures for BYOAI [@jlengelbrecht](https://github.com/jlengelbrecht) ([#634](https://github.com/GlycemicGPT/GlycemicGPT/pull/634))
- feat(api, web): hero card closed-loop surfaces (43.12 PR 6) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#633](https://github.com/GlycemicGPT/GlycemicGPT/pull/633))

#### 🐛 Bug Fixes

- fix: loud signals for COOKIE_SECURE plain-HTTP deploy misconfig [@jlengelbrecht](https://github.com/jlengelbrecht) ([#637](https://github.com/GlycemicGPT/GlycemicGPT/pull/637))

#### 📝 Other Changes

- fix(web): improve dashboard mobile responsiveness [@SleightOS](https://github.com/SleightOS) ([#638](https://github.com/GlycemicGPT/GlycemicGPT/pull/638))

### 📡 API

#### ✨ New Features

- feat(api): forecast read endpoint + picker preference (43.12 PR 3) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#635](https://github.com/GlycemicGPT/GlycemicGPT/pull/635))
- feat(api): forecast translator extension (43.12 PR 2) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#615](https://github.com/GlycemicGPT/GlycemicGPT/pull/615))

### 🏗️ Infrastructure

#### 📝 Other Changes

- chore: sync changelog update from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#631](https://github.com/GlycemicGPT/GlycemicGPT/pull/631))

### ❓ Uncategorized

- chore(security): suppress ZAP 10111 + document GitHub-native scanners [@jlengelbrecht](https://github.com/jlengelbrecht) ([#646](https://github.com/GlycemicGPT/GlycemicGPT/pull/646))
- Pin requests-oidc floor to >=0.6.0 to block silent downgrade [@jlengelbrecht](https://github.com/jlengelbrecht) ([#643](https://github.com/GlycemicGPT/GlycemicGPT/pull/643))
- Expand Dexcom + Tandem region support and fix Tandem cloud upload [@jlengelbrecht](https://github.com/jlengelbrecht) ([#642](https://github.com/GlycemicGPT/GlycemicGPT/pull/642))
- docs: add Supported by section and scope-down sponsor/credential docs [@jlengelbrecht](https://github.com/jlengelbrecht) ([#641](https://github.com/GlycemicGPT/GlycemicGPT/pull/641))
- ci: support fork PRs in labeler, attribution check, and security scan [@jlengelbrecht](https://github.com/jlengelbrecht) ([#639](https://github.com/GlycemicGPT/GlycemicGPT/pull/639))

<!-- changelog-cutoff:2026-05-18T13:14:01Z -->


## 2026-05-13

### 📱 Mobile

#### 📝 Other Changes

- chore: sync release 0.7.1 from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#626](https://github.com/GlycemicGPT/GlycemicGPT/pull/626))

### 🏗️ Infrastructure

#### 📝 Other Changes

- chore: sync changelog update from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#625](https://github.com/GlycemicGPT/GlycemicGPT/pull/625))

### ❓ Uncategorized

- fix(funding): trim managed-cloud-platform plan description to under 500 chars [@jlengelbrecht](https://github.com/jlengelbrecht) ([#627](https://github.com/GlycemicGPT/GlycemicGPT/pull/627))

<!-- changelog-cutoff:2026-05-13T23:20:07Z -->


## 2026-05-13

### 📱 Mobile

#### 📝 Other Changes

- chore: sync release 0.7.0 from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#620](https://github.com/GlycemicGPT/GlycemicGPT/pull/620))

### 🏗️ Infrastructure

#### 📝 Other Changes

- chore: sync changelog update from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#619](https://github.com/GlycemicGPT/GlycemicGPT/pull/619))

### ❓ Uncategorized

- fix(funding): make funding.json compliant with fundingjson.org v1.1.0 schema [@jlengelbrecht](https://github.com/jlengelbrecht) ([#621](https://github.com/GlycemicGPT/GlycemicGPT/pull/621))

<!-- changelog-cutoff:2026-05-13T20:35:46Z -->


## 2026-05-13

### 🌐 Web

#### ✨ New Features

- feat(web): Nightscout re-import entry point on existing connection cards (43.7d) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#612](https://github.com/GlycemicGPT/GlycemicGPT/pull/612))

#### 🐛 Bug Fixes

- fix(web): hide soft-deleted Nightscout connections from the list [@jlengelbrecht](https://github.com/jlengelbrecht) ([#610](https://github.com/GlycemicGPT/GlycemicGPT/pull/610))

### 📡 API

#### ✨ New Features

- feat(api): forecast_snapshots + forecast_evaluations schema (43.12 PR 1) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#613](https://github.com/GlycemicGPT/GlycemicGPT/pull/613))

#### 🐛 Bug Fixes

- fix(nightscout): swap entries cursor to NS Mongo `_id` (closes #598) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#611](https://github.com/GlycemicGPT/GlycemicGPT/pull/611))

### 🏗️ Infrastructure

#### 💥 Breaking Changes

- fix(ci): single-shot release-body extraction (no historical bleed) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#605](https://github.com/GlycemicGPT/GlycemicGPT/pull/605))

### 📚 Documentation

- docs: add funding.json manifest and align funding sections with Open Source Collective [@jlengelbrecht](https://github.com/jlengelbrecht) ([#614](https://github.com/GlycemicGPT/GlycemicGPT/pull/614))

<!-- changelog-cutoff:2026-05-13T06:58:03Z -->


## 2026-05-11

### 📱 Mobile

#### 🐛 Bug Fixes

- fix(mobile): serialize token refresh under a single mutex (closes #520) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#555](https://github.com/GlycemicGPT/GlycemicGPT/pull/555))

#### 📝 Other Changes

- chore: sync release 0.5.0 from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#532](https://github.com/GlycemicGPT/GlycemicGPT/pull/532))

### 🌐 Web

#### ✨ New Features

- feat(web): Nightscout smart-onboarding wizard route + 5 steps [@jlengelbrecht](https://github.com/jlengelbrecht) ([#597](https://github.com/GlycemicGPT/GlycemicGPT/pull/597))
- feat: sync interval picker + per-source freshness card [@jlengelbrecht](https://github.com/jlengelbrecht) ([#578](https://github.com/GlycemicGPT/GlycemicGPT/pull/578))
- feat: Nightscout connection management UI + manual sync trigger [@jlengelbrecht](https://github.com/jlengelbrecht) ([#575](https://github.com/GlycemicGPT/GlycemicGPT/pull/575))

#### 🐛 Bug Fixes

- fix(#554): configurable max_response_tokens for thinking models [@jlengelbrecht](https://github.com/jlengelbrecht) ([#600](https://github.com/GlycemicGPT/GlycemicGPT/pull/600))
- fix(api): repair bootstrap knowledge seed (closes #563) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#567](https://github.com/GlycemicGPT/GlycemicGPT/pull/567))
- fix(deps): clear OSV-flagged CVEs in lockfiles [@jlengelbrecht](https://github.com/jlengelbrecht) ([#535](https://github.com/GlycemicGPT/GlycemicGPT/pull/535))

### 📡 API

#### ✨ New Features

- feat(api): Nightscout apply-onboarding endpoint + derivation read [@jlengelbrecht](https://github.com/jlengelbrecht) ([#596](https://github.com/GlycemicGPT/GlycemicGPT/pull/596))
- feat(api): pure-function NS profile -> wizard proposals derive [@jlengelbrecht](https://github.com/jlengelbrecht) ([#595](https://github.com/GlycemicGPT/GlycemicGPT/pull/595))
- feat(api): Nightscout evaluate endpoint for smart-onboarding wizard (Story 43.7a) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#594](https://github.com/GlycemicGPT/GlycemicGPT/pull/594))
- feat(dev): tconnectsync lens — Tandem t:connect cloud → NS bridge (pump-side) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#591](https://github.com/GlycemicGPT/GlycemicGPT/pull/591))
- feat(dev): AAPS v1 lens + extractor handles openaps.enacted.rate [@jlengelbrecht](https://github.com/jlengelbrecht) ([#583](https://github.com/GlycemicGPT/GlycemicGPT/pull/583))
- feat: Nightscout background sync scheduler [@jlengelbrecht](https://github.com/jlengelbrecht) ([#576](https://github.com/GlycemicGPT/GlycemicGPT/pull/576))
- feat(api): Nightscout translator orchestrator + ORM mapping layer [@jlengelbrecht](https://github.com/jlengelbrecht) ([#572](https://github.com/GlycemicGPT/GlycemicGPT/pull/572))
- feat(api): typed Pydantic input models for Nightscout wire shapes [@jlengelbrecht](https://github.com/jlengelbrecht) ([#571](https://github.com/GlycemicGPT/GlycemicGPT/pull/571))
- feat(api): Nightscout v1+v3 read client + SSRF guard [@jlengelbrecht](https://github.com/jlengelbrecht) ([#570](https://github.com/GlycemicGPT/GlycemicGPT/pull/570))
- feat(api): Nightscout connection model + endpoints [@jlengelbrecht](https://github.com/jlengelbrecht) ([#568](https://github.com/GlycemicGPT/GlycemicGPT/pull/568))

#### 🐛 Bug Fixes

- fix(nightscout): promote pump telemetry to pump_events for dashboard [@jlengelbrecht](https://github.com/jlengelbrecht) ([#582](https://github.com/GlycemicGPT/GlycemicGPT/pull/582))
- fix(nightscout): scheduler tick wall budget + test fixture hardening [@jlengelbrecht](https://github.com/jlengelbrecht) ([#580](https://github.com/GlycemicGPT/GlycemicGPT/pull/580))
- fix: source-agnostic Insulin Summary + Recent Boluses widgets [@jlengelbrecht](https://github.com/jlengelbrecht) ([#577](https://github.com/GlycemicGPT/GlycemicGPT/pull/577))

### 🔒 Security

#### 📝 Other Changes

- chore(deps): pin dependencies - abandoned [@glycemicgpt-renovate](https://github.com/glycemicgpt-renovate) ([#543](https://github.com/GlycemicGPT/GlycemicGPT/pull/543))
- ci(security): GitHub Actions supply-chain hygiene [@jlengelbrecht](https://github.com/jlengelbrecht) ([#541](https://github.com/GlycemicGPT/GlycemicGPT/pull/541))
- chore(deps): update actions/checkout action to v6 [@glycemicgpt-renovate](https://github.com/glycemicgpt-renovate) ([#539](https://github.com/GlycemicGPT/GlycemicGPT/pull/539))

### 🏗️ Infrastructure

#### 🐛 Bug Fixes

- fix(ci): switch container cleanup to tag-aware action (re #550) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#552](https://github.com/GlycemicGPT/GlycemicGPT/pull/552))

#### 📝 Other Changes

- ci: address CodeRabbit findings on promotion PR #548 [@jlengelbrecht](https://github.com/jlengelbrecht) ([#549](https://github.com/GlycemicGPT/GlycemicGPT/pull/549))
- ci: phase 5 -- enable Renovate auto-merge via label-driven workflow [@jlengelbrecht](https://github.com/jlengelbrecht) ([#547](https://github.com/GlycemicGPT/GlycemicGPT/pull/547))
- ci: phase 4 -- group Renovate PRs by family [@jlengelbrecht](https://github.com/jlengelbrecht) ([#546](https://github.com/GlycemicGPT/GlycemicGPT/pull/546))
- ci: phase 2 -- fork PR lockdown (CODEOWNERS + Renovate caps) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#545](https://github.com/GlycemicGPT/GlycemicGPT/pull/545))
- ci: path-filter ci.yml component test/lint jobs [@jlengelbrecht](https://github.com/jlengelbrecht) ([#544](https://github.com/GlycemicGPT/GlycemicGPT/pull/544))
- ci(renovate): add log_level workflow_dispatch input for diagnostic runs [@jlengelbrecht](https://github.com/jlengelbrecht) ([#538](https://github.com/GlycemicGPT/GlycemicGPT/pull/538))
- chore: sync changelog update from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#531](https://github.com/GlycemicGPT/GlycemicGPT/pull/531))

### 📚 Documentation

- docs: add Integrations page covering Nightscout + reflect live integration [@jlengelbrecht](https://github.com/jlengelbrecht) ([#599](https://github.com/GlycemicGPT/GlycemicGPT/pull/599))
- feat(dev): ns_emulator interactive --wizard mode for new contributors [@jlengelbrecht](https://github.com/jlengelbrecht) ([#593](https://github.com/GlycemicGPT/GlycemicGPT/pull/593))
- feat(dev): manual lens — Care Portal direct-entry web UI (final lens) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#592](https://github.com/GlycemicGPT/GlycemicGPT/pull/592))
- feat(dev): share2ns lens — Dexcom Share cloud → NS bridge [@jlengelbrecht](https://github.com/jlengelbrecht) ([#590](https://github.com/GlycemicGPT/GlycemicGPT/pull/590))
- feat(dev): LibreLinkUp lens — Abbott cloud → NS bridge (entries-only) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#589](https://github.com/GlycemicGPT/GlycemicGPT/pull/589))
- feat(dev): xDrip+ lens — Android pure-CGM uploader [@jlengelbrecht](https://github.com/jlengelbrecht) ([#588](https://github.com/GlycemicGPT/GlycemicGPT/pull/588))
- feat(dev): xDrip4iOS lens — pure-CGM iOS uploader (no closed-loop) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#587](https://github.com/GlycemicGPT/GlycemicGPT/pull/587))
- feat(dev): oref0 lens — original OpenAPS Raspberry Pi wire format [@jlengelbrecht](https://github.com/jlengelbrecht) ([#586](https://github.com/GlycemicGPT/GlycemicGPT/pull/586))
- feat(dev): Trio lens — iOS oref-derived closed-loop wire format [@jlengelbrecht](https://github.com/jlengelbrecht) ([#585](https://github.com/GlycemicGPT/GlycemicGPT/pull/585))
- feat(dev): AAPS v3 lens — NSClientV3 wire format (API v3 + JWT) [@jlengelbrecht](https://github.com/jlengelbrecht) ([#584](https://github.com/GlycemicGPT/GlycemicGPT/pull/584))
- feat(dev): multi-lens Nightscout emulator with Loop lens [@jlengelbrecht](https://github.com/jlengelbrecht) ([#581](https://github.com/GlycemicGPT/GlycemicGPT/pull/581))
- docs(readme): align positioning with docs — AI-first, ecosystem-aware [@jlengelbrecht](https://github.com/jlengelbrecht) ([#551](https://github.com/GlycemicGPT/GlycemicGPT/pull/551))
- docs(security): add Dependency Auto-Merge Coverage contract [@jlengelbrecht](https://github.com/jlengelbrecht) ([#540](https://github.com/GlycemicGPT/GlycemicGPT/pull/540))

<!-- changelog-cutoff:2026-05-11T06:11:31Z -->


## 2026-04-30

### 📱 Mobile

#### 💥 Breaking Changes

- docs: align repo with monitoring-only positioning + add ROADMAP.md [@jlengelbrecht](https://github.com/jlengelbrecht) ([#514](https://github.com/GlycemicGPT/GlycemicGPT/pull/514))

#### 📝 Other Changes

- chore: sync release 0.4.1 from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#525](https://github.com/GlycemicGPT/GlycemicGPT/pull/525))
- chore: sync release 0.4.0 from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#509](https://github.com/GlycemicGPT/GlycemicGPT/pull/509))
- chore: sync release 0.3.3 from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#501](https://github.com/GlycemicGPT/GlycemicGPT/pull/501))

### ⌚ Wear OS

#### 🐛 Bug Fixes

- fix(ci): include wear-device and watchface in version bumps [@jlengelbrecht](https://github.com/jlengelbrecht) ([#503](https://github.com/GlycemicGPT/GlycemicGPT/pull/503))

### 📡 API

#### 🐛 Bug Fixes

- fix(ai): update test assertions for sidecar API key auth change [@jlengelbrecht](https://github.com/jlengelbrecht) ([#510](https://github.com/GlycemicGPT/GlycemicGPT/pull/510))
- fix(ai): use sidecar API key for subscription chat auth [@jlengelbrecht](https://github.com/jlengelbrecht) ([#505](https://github.com/GlycemicGPT/GlycemicGPT/pull/505))

#### 📝 Other Changes

- docs: phase 1 rewrite — non-technical user track + community-facing docs [@jlengelbrecht](https://github.com/jlengelbrecht) ([#522](https://github.com/GlycemicGPT/GlycemicGPT/pull/522))

### 🏗️ Infrastructure

#### ✨ New Features

- feat(ci): include watchface APKs in release builds [@jlengelbrecht](https://github.com/jlengelbrecht) ([#502](https://github.com/GlycemicGPT/GlycemicGPT/pull/502))

#### 📝 Other Changes

- chore: sync changelog update from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#500](https://github.com/GlycemicGPT/GlycemicGPT/pull/500))

### 📚 Documentation

- docs: clarify GitHub branch-counter artifact + fix flow diagram [@jlengelbrecht](https://github.com/jlengelbrecht) ([#517](https://github.com/GlycemicGPT/GlycemicGPT/pull/517))
- docs(roadmap): early adopter feedback additions + conversational channel expansion [@jlengelbrecht](https://github.com/jlengelbrecht) ([#515](https://github.com/GlycemicGPT/GlycemicGPT/pull/515))
- docs(readme): reposition Mobi note as monitoring-only and add Discord community link [@jlengelbrecht](https://github.com/jlengelbrecht) ([#511](https://github.com/GlycemicGPT/GlycemicGPT/pull/511))

<!-- changelog-cutoff:2026-04-30T21:30:23Z -->


## 2026-04-06

### 📱 Mobile

#### 🐛 Bug Fixes

- fix(mobile): add R8 keep rules for wear release APK build [@jlengelbrecht](https://github.com/jlengelbrecht) ([#496](https://github.com/GlycemicGPT/GlycemicGPT/pull/496))

#### 📝 Other Changes

- chore: sync release 0.3.2 from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#495](https://github.com/GlycemicGPT/GlycemicGPT/pull/495))
- chore: sync release 0.3.1 from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#490](https://github.com/GlycemicGPT/GlycemicGPT/pull/490))

### 🏗️ Infrastructure

#### 🐛 Bug Fixes

- fix(ci): gate fallback release on deployable code changes [@jlengelbrecht](https://github.com/jlengelbrecht) ([#492](https://github.com/GlycemicGPT/GlycemicGPT/pull/492))

#### 📝 Other Changes

- chore: sync changelog update from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#489](https://github.com/GlycemicGPT/GlycemicGPT/pull/489))

### 📚 Documentation

- fix: CodeRabbit badge showing provider not found [@jlengelbrecht](https://github.com/jlengelbrecht) ([#491](https://github.com/GlycemicGPT/GlycemicGPT/pull/491))

<!-- changelog-cutoff:2026-04-06T06:07:10Z -->


## 2026-04-06

### 🏗️ Infrastructure

#### 🐛 Bug Fixes

- fix: close CODEOWNERS self-review loophole, align with governance [@jlengelbrecht](https://github.com/jlengelbrecht) ([#485](https://github.com/GlycemicGPT/GlycemicGPT/pull/485))
- fix(ci): idempotent fallback release on workflow rerun [@jlengelbrecht](https://github.com/jlengelbrecht) ([#484](https://github.com/GlycemicGPT/GlycemicGPT/pull/484))
- fix(ci): smart versioning with fallback patch release for every promotion [@jlengelbrecht](https://github.com/jlengelbrecht) ([#481](https://github.com/GlycemicGPT/GlycemicGPT/pull/481))

#### 📝 Other Changes

- chore: sync changelog update from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#480](https://github.com/GlycemicGPT/GlycemicGPT/pull/480))

<!-- changelog-cutoff:2026-04-06T01:13:52Z -->


## 2026-04-05

### 🏗️ Infrastructure

#### 📝 Other Changes

- chore: new slogan, align merge docs, fix changelog heading format [@jlengelbrecht](https://github.com/jlengelbrecht) ([#477](https://github.com/GlycemicGPT/GlycemicGPT/pull/477))

<!-- changelog-cutoff:2026-04-05T06:16:36Z -->


## 2026-04-04

### 📱 Mobile

  - #### 📝 Other Changes

    - chore: sync release 0.2.0 from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#471](https://github.com/GlycemicGPT/GlycemicGPT/pull/471))

### 🏗️ Infrastructure

  - #### ✨ New Features

    - feat(ci): contributor credits in versioned releases, soft-fail wear APK [@jlengelbrecht](https://github.com/jlengelbrecht) ([#473](https://github.com/GlycemicGPT/GlycemicGPT/pull/473))

  - #### 📝 Other Changes

    - chore: sync changelog update from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#469](https://github.com/GlycemicGPT/GlycemicGPT/pull/469))

<!-- changelog-cutoff:2026-04-04T06:49:57Z -->


## 2026-04-04

### 🏗️ Infrastructure

  - #### 🐛 Bug Fixes

    - fix(ci): changelog CodeRabbit findings - tag collision, timezone, database scope [@jlengelbrecht](https://github.com/jlengelbrecht) ([#463](https://github.com/GlycemicGPT/GlycemicGPT/pull/463))

  - #### 📝 Other Changes

    - chore: sync changelog update from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#462](https://github.com/GlycemicGPT/GlycemicGPT/pull/462))

<!-- changelog-cutoff:2026-04-04T04:53:06Z -->


## 2026-04-03

### 🏗️ Infrastructure

  - #### 💥 Breaking Changes

    - feat(ci): ProxmoxVE-style changelog with emojis, sub-categories, and releases [@jlengelbrecht](https://github.com/jlengelbrecht) ([#459](https://github.com/GlycemicGPT/GlycemicGPT/pull/459))

  - #### 📝 Other Changes

    - chore: sync changelog update from main to develop [@glycemicgpt-merge](https://github.com/glycemicgpt-merge) ([#458](https://github.com/GlycemicGPT/GlycemicGPT/pull/458))

<!-- changelog-cutoff:2026-04-04T01:57:44Z -->


Entries are generated automatically from PRs merged to develop on each promotion to main.
Contributors are credited by their GitHub username.

See [Releases](https://github.com/GlycemicGPT/GlycemicGPT/releases) for downloadable artifacts.

<!-- changelog-cutoff:2026-04-03T19:58:00Z -->
