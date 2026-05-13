# Changelog

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
