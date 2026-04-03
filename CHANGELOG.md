<div align="center">
  <h1>📋 Changelog</h1>
  <p><strong>GlycemicGPT</strong> - Your AI-powered diabetes management companion</p>
  <p>
    <a href="https://github.com/jlengelbrecht/GlycemicGPT/releases">
      <img src="https://img.shields.io/github/v/release/jlengelbrecht/GlycemicGPT?style=flat-square&color=blue" alt="Latest Release">
    </a>
  </p>
</div>

> [!NOTE]
> All notable changes to this project will be documented in this file.
> This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.100](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.99...v0.1.100) (2026-02-21)


### 🐛 Bug Fixes

* align Renovate config with develop-first branching strategy ([#273](https://github.com/jlengelbrecht/GlycemicGPT/issues/273)) ([46879a3](https://github.com/jlengelbrecht/GlycemicGPT/commit/46879a3f86a7450ceecd0ffb5fff374f0776919d))

## [0.1.99](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.98...v0.1.99) (2026-02-21)


### ✨ Features

* add guided onboarding flow and CodeRabbit configuration ([#268](https://github.com/jlengelbrecht/GlycemicGPT/issues/268)) ([f7eed66](https://github.com/jlengelbrecht/GlycemicGPT/commit/f7eed66e506dba2c5cdac334c7a2cabb73d72a6b))


### 🐛 Bug Fixes

* address second-pass CodeRabbit review findings ([cfbcfbc](https://github.com/jlengelbrecht/GlycemicGPT/commit/cfbcfbc7d6b9c35bb8c2ffd5a7be7034d7d77bb3))
* address third-pass CodeRabbit review findings ([43bf4dc](https://github.com/jlengelbrecht/GlycemicGPT/commit/43bf4dc032d3ae2258dda8cf4435ddc388dc0b15))
* apply CodeRabbit review hardening fixes ([346d863](https://github.com/jlengelbrecht/GlycemicGPT/commit/346d863c4b4325ce826d50b5281615a2d18d9978))
* bypass broken paths-filter for develop branch container builds ([#269](https://github.com/jlengelbrecht/GlycemicGPT/issues/269)) ([a163a34](https://github.com/jlengelbrecht/GlycemicGPT/commit/a163a348f37fcb06324b1b5a683fa368035b3aed))
* harden onboarding flow and add markdown rendering for AI responses ([#270](https://github.com/jlengelbrecht/GlycemicGPT/issues/270)) ([19c29a3](https://github.com/jlengelbrecht/GlycemicGPT/commit/19c29a36ec62a5db74b8a528667ce788da9864db))
* make Dev Build badge dynamic and show CodeRabbit review count ([34af278](https://github.com/jlengelbrecht/GlycemicGPT/commit/34af278dff19e6333fac0cd18e3521d0f736dd9f))


### 📚 Documentation

* add shields.io status badges to README ([b4acfb2](https://github.com/jlengelbrecht/GlycemicGPT/commit/b4acfb2fa4830eb8050c1057f99cad6a13016d88))

## [0.1.98](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.97...v0.1.98) (2026-02-20)


### 🐛 Bug Fixes

* add DEV_BUILD_NUMBER to release build config ([#259](https://github.com/jlengelbrecht/GlycemicGPT/issues/259)) ([d45570b](https://github.com/jlengelbrecht/GlycemicGPT/commit/d45570bd681412ec052a42f513c774700e15b3ee))

## [0.1.97](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.96...v0.1.97) (2026-02-20)


### 📚 Documentation

* add contributing guide, improve issue templates, update README ([#256](https://github.com/jlengelbrecht/GlycemicGPT/issues/256)) ([a33651a](https://github.com/jlengelbrecht/GlycemicGPT/commit/a33651afa5180bd9a778e81522e0d66b15c5abba))

## [0.1.96](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.95...v0.1.96) (2026-02-20)


### ✨ Features

* add develop/main branching strategy with dev release channels ([#254](https://github.com/jlengelbrecht/GlycemicGPT/issues/254)) ([54efa66](https://github.com/jlengelbrecht/GlycemicGPT/commit/54efa66caf370fb1c45de73db45dc36a38a8778f))
* add time in range bar and move pump status into hero card ([#237](https://github.com/jlengelbrecht/GlycemicGPT/issues/237)) ([7169533](https://github.com/jlengelbrecht/GlycemicGPT/commit/71695333c13bd08300c33b3358fd8bc3c3c94dc3))
* BLE history backfill, chart overlays, pump status hero, and V2 bolus parser fix ([#252](https://github.com/jlengelbrecht/GlycemicGPT/issues/252)) ([a6fcc0a](https://github.com/jlengelbrecht/GlycemicGPT/commit/a6fcc0ad507b8b6666015953d2b4d8d3ecfceb1a))
* glucose trend chart with basal/bolus overlays for mobile home ([#236](https://github.com/jlengelbrecht/GlycemicGPT/issues/236)) ([62c0f9a](https://github.com/jlengelbrecht/GlycemicGPT/commit/62c0f9a936bf12dd49cfa375fb84bac64c4df837))
* make glucose thresholds dynamic from backend settings ([#241](https://github.com/jlengelbrecht/GlycemicGPT/issues/241)) ([36bb020](https://github.com/jlengelbrecht/GlycemicGPT/commit/36bb0203dd45eac71916bd100acb6c7ac73fb7ef))
* tiered BLE reconnection with indefinite slow phase ([#244](https://github.com/jlengelbrecht/GlycemicGPT/issues/244)) ([1801393](https://github.com/jlengelbrecht/GlycemicGPT/commit/180139374db68afedb9af207009023ca53134bde))


### 🐛 Bug Fixes

* **deps:** update dependency next to v15.5.12 ([#233](https://github.com/jlengelbrecht/GlycemicGPT/issues/233)) ([94b4cad](https://github.com/jlengelbrecht/GlycemicGPT/commit/94b4cadffb9ed21483fb2020308ba507c9cb91e5))
* use dynamic glucose thresholds in Time in Range pipeline ([#242](https://github.com/jlengelbrecht/GlycemicGPT/issues/242)) ([83bd5ab](https://github.com/jlengelbrecht/GlycemicGPT/commit/83bd5ab62b1e5c8fcea05786ea872c7aa51f63df))


### 👷 CI/CD

* add attribution guardrails -- commit-msg hook and CI check ([#231](https://github.com/jlengelbrecht/GlycemicGPT/issues/231)) ([aa11e82](https://github.com/jlengelbrecht/GlycemicGPT/commit/aa11e829347cc95edbe9fc2ab4726c633fc28ade))

## [0.1.95](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.94...v0.1.95) (2026-02-17)


### ✨ Features

* add AI insight card and unified insights feed (Story 5.7) ([#44](https://github.com/jlengelbrecht/GlycemicGPT/issues/44)) ([c2f9d6f](https://github.com/jlengelbrecht/GlycemicGPT/commit/c2f9d6fb8121baa52a04ef26ca976b91114207a8))
* add AI provider configuration page (Story 11.1) ([#117](https://github.com/jlengelbrecht/GlycemicGPT/issues/117)) ([ab6886d](https://github.com/jlengelbrecht/GlycemicGPT/commit/ab6886d9b3a41c50a3342d215b6d5a9e8f187a7c))
* add AI reasoning display and audit logging (Story 5.8) ([#46](https://github.com/jlengelbrecht/GlycemicGPT/issues/46)) ([48d32c1](https://github.com/jlengelbrecht/GlycemicGPT/commit/48d32c1c4768ff0fa3ffc6f6045a15f1bde98ee7))
* add AI sidecar container image (Story 15.1) ([#147](https://github.com/jlengelbrecht/GlycemicGPT/issues/147)) ([ca42b12](https://github.com/jlengelbrecht/GlycemicGPT/commit/ca42b126be3144b637a65ecdd82e17dbb2edbda4))
* add ai-sidecar to docker compose for all environments (Story 15.3) ([#151](https://github.com/jlengelbrecht/GlycemicGPT/issues/151)) ([917c2dd](https://github.com/jlengelbrecht/GlycemicGPT/commit/917c2dd03ce47363d0b1dbafe6baff084abcd26c))
* add alert settings page for thresholds and escalation (Story 10.3) ([#107](https://github.com/jlengelbrecht/GlycemicGPT/issues/107)) ([0b81817](https://github.com/jlengelbrecht/GlycemicGPT/commit/0b8181753b012341cb0377e128e65ee3cfa06a22))
* add alert threshold configuration (Story 6.1) ([#48](https://github.com/jlengelbrecht/GlycemicGPT/issues/48)) ([1973b20](https://github.com/jlengelbrecht/GlycemicGPT/commit/1973b20cab42381c88d967544f41bb922527f216))
* add auth middleware for route protection (Story 15.3) ([#134](https://github.com/jlengelbrecht/GlycemicGPT/issues/134)) ([85e4ed7](https://github.com/jlengelbrecht/GlycemicGPT/commit/85e4ed7776c6232533c35f09e763d61ea8a1c1e9))
* add auth token persistence and proactive refresh for mobile app ([#229](https://github.com/jlengelbrecht/GlycemicGPT/issues/229)) ([2157502](https://github.com/jlengelbrecht/GlycemicGPT/commit/215750278cd48bacdfd2a6c3a818a4401d16b71a))
* add automatic escalation to caregivers (Story 6.7) ([#60](https://github.com/jlengelbrecht/GlycemicGPT/issues/60)) ([35d8128](https://github.com/jlengelbrecht/GlycemicGPT/commit/35d8128e280ac04c1e6a8ab6096263e0cb98fa42))
* add caregiver account creation and linking (Story 8.1) ([#78](https://github.com/jlengelbrecht/GlycemicGPT/issues/78)) ([6002334](https://github.com/jlengelbrecht/GlycemicGPT/commit/600233454aec009bfe58ce5088e985679342ad4e))
* add caregiver AI chat for patient queries (Story 8.4) ([#84](https://github.com/jlengelbrecht/GlycemicGPT/issues/84)) ([219617e](https://github.com/jlengelbrecht/GlycemicGPT/commit/219617e81e761354d6f080a8e84491731a6ab24a))
* add caregiver dashboard view (Story 8.3) ([#82](https://github.com/jlengelbrecht/GlycemicGPT/issues/82)) ([44cbb0a](https://github.com/jlengelbrecht/GlycemicGPT/commit/44cbb0a73f4e9c1f066ffdf17e9a545e9eca52c9))
* add caregiver data access permission management (Story 8.2) ([#80](https://github.com/jlengelbrecht/GlycemicGPT/issues/80)) ([d2fd8f3](https://github.com/jlengelbrecht/GlycemicGPT/commit/d2fd8f369d7a5153381602eabf8458804458a5e5))
* add communications settings hub page (Story 12.2) ([#113](https://github.com/jlengelbrecht/GlycemicGPT/issues/113)) ([e9f4d36](https://github.com/jlengelbrecht/GlycemicGPT/commit/e9f4d36476a21046506236b86a0af876b2a80019))
* add daily brief delivery configuration (Story 9.2) ([#92](https://github.com/jlengelbrecht/GlycemicGPT/issues/92)) ([6fd582d](https://github.com/jlengelbrecht/GlycemicGPT/commit/6fd582d91e3bfd140fe06f031f9348675ec7680c))
* add data purge capability (Story 9.4) ([#96](https://github.com/jlengelbrecht/GlycemicGPT/issues/96)) ([a1697a3](https://github.com/jlengelbrecht/GlycemicGPT/commit/a1697a37004e53e2476e61a496bcbc224ef3cc60))
* add data retention settings (Story 9.3) ([#94](https://github.com/jlengelbrecht/GlycemicGPT/issues/94)) ([5334782](https://github.com/jlengelbrecht/GlycemicGPT/commit/5334782eb75c1d190a21ed89d22eaa24e798ca24))
* add Dexcom-style glucose trend chart to dashboard ([#143](https://github.com/jlengelbrecht/GlycemicGPT/issues/143)) ([200c469](https://github.com/jlengelbrecht/GlycemicGPT/commit/200c46975367f64e8c3c84f8fa3b63f4a815fea8))
* add Docker container integration testing (Story 13.2) ([#124](https://github.com/jlengelbrecht/GlycemicGPT/issues/124)) ([ad74d45](https://github.com/jlengelbrecht/GlycemicGPT/commit/ad74d453418e6787a990254bfb5e394798c4e61e))
* add emergency contact configuration (Story 6.5) ([#56](https://github.com/jlengelbrecht/GlycemicGPT/issues/56)) ([82ed919](https://github.com/jlengelbrecht/GlycemicGPT/commit/82ed919b01429faad4d9d698cdfc8095ff03c7ac))
* add escalation timing configuration (Story 6.6) ([#58](https://github.com/jlengelbrecht/GlycemicGPT/issues/58)) ([85d7870](https://github.com/jlengelbrecht/GlycemicGPT/commit/85d78705f1b7c35c1427d58c3a1356fa8d23042d))
* add FastAPI backend, Next.js frontend, and K8s deployment ([651de00](https://github.com/jlengelbrecht/GlycemicGPT/commit/651de00b40aea174d50c02a4799fd697feb6185b))
* add GitHub self-update mechanism (Story 16.13) ([#187](https://github.com/jlengelbrecht/GlycemicGPT/issues/187)) ([3fe0627](https://github.com/jlengelbrecht/GlycemicGPT/commit/3fe062759dd8d6536afbcb01fab4f52755eeb19c))
* add graceful offline/disconnected state to all settings pages (Story 12.4) ([#111](https://github.com/jlengelbrecht/GlycemicGPT/issues/111)) ([50cff49](https://github.com/jlengelbrecht/GlycemicGPT/commit/50cff49030f301631115e85996547f7f27a88af2))
* add integrations settings page for Dexcom and Tandem (Story 12.1) ([#109](https://github.com/jlengelbrecht/GlycemicGPT/issues/109)) ([f6bdfb4](https://github.com/jlengelbrecht/GlycemicGPT/commit/f6bdfb49a6aa2686d8e3fb0c241aaf078ed0715f))
* add local dev server testing checklist and smoke tests (Story 13.1) ([#123](https://github.com/jlengelbrecht/GlycemicGPT/issues/123)) ([36205f5](https://github.com/jlengelbrecht/GlycemicGPT/commit/36205f56af869b0955177eebd1db337aeca15b1f))
* add login page with email/password authentication (Story 15.1) ([#130](https://github.com/jlengelbrecht/GlycemicGPT/issues/130)) ([c44ba12](https://github.com/jlengelbrecht/GlycemicGPT/commit/c44ba12ae09896e544b0f7ef385cbc9fab321583))
* add logout, auth state display, and global 401 handling (Story 15.4) ([#136](https://github.com/jlengelbrecht/GlycemicGPT/issues/136)) ([aee92f5](https://github.com/jlengelbrecht/GlycemicGPT/commit/aee92f5e17fafe7147e69262955ebbd8cf823190))
* add post-login disclaimer enforcement (Story 15.5) ([#138](https://github.com/jlengelbrecht/GlycemicGPT/issues/138)) ([0eb872f](https://github.com/jlengelbrecht/GlycemicGPT/commit/0eb872fa50d8290629db3697cc5e9555ed7d8890))
* add predictive alert engine with IoB escalation (Story 6.2) ([#50](https://github.com/jlengelbrecht/GlycemicGPT/issues/50)) ([b35cb05](https://github.com/jlengelbrecht/GlycemicGPT/commit/b35cb05059eb2d38c9ace5097599e10c36f2c9ae))
* add profile settings page with display name and password change (Story 10.2) ([#105](https://github.com/jlengelbrecht/GlycemicGPT/issues/105)) ([3f3bb4a](https://github.com/jlengelbrecht/GlycemicGPT/commit/3f3bb4ab1adcb2c6ae128c11aa728c542e734d55))
* add real data pipeline verification script (Story 13.3) ([#125](https://github.com/jlengelbrecht/GlycemicGPT/issues/125)) ([0b5a102](https://github.com/jlengelbrecht/GlycemicGPT/commit/0b5a102333a9bf0234dbed03760eb1de278b3803))
* add real-time data polling and local Room storage (Story 16.4) ([#173](https://github.com/jlengelbrecht/GlycemicGPT/issues/173)) ([5bff9d8](https://github.com/jlengelbrecht/GlycemicGPT/commit/5bff9d8af54f03c92068ff74dd24d3fe91c9b702))
* add real-time glucose updates via SSE (Story 4.5) ([#26](https://github.com/jlengelbrecht/GlycemicGPT/issues/26)) ([b8edecb](https://github.com/jlengelbrecht/GlycemicGPT/commit/b8edecbc2da5ebed709f5bd93cbba665fdaa1e67))
* add registration page with password strength indicators (Story 15.2) ([#132](https://github.com/jlengelbrecht/GlycemicGPT/issues/132)) ([023cebf](https://github.com/jlengelbrecht/GlycemicGPT/commit/023cebf78fed3d563596e0d2875c2d699dec74a7))
* add security hardening with token refresh, rate limiting, and TLS (Story 16.12) ([#194](https://github.com/jlengelbrecht/GlycemicGPT/issues/194)) ([320e7d5](https://github.com/jlengelbrecht/GlycemicGPT/commit/320e7d5eac896b985e40a923c16a48edad56d43d))
* add settings export capability (Story 9.5) ([#98](https://github.com/jlengelbrecht/GlycemicGPT/issues/98)) ([d36b6a4](https://github.com/jlengelbrecht/GlycemicGPT/commit/d36b6a480cb6ab4b1e0cdffa56b1467a920a4904))
* add sidecar_provider column and make encrypted_api_key nullable (Story 15.7) ([#153](https://github.com/jlengelbrecht/GlycemicGPT/issues/153)) ([32a8f47](https://github.com/jlengelbrecht/GlycemicGPT/commit/32a8f47e76c29ec38818739e2f0a8b6d91e6f058))
* add target glucose range configuration (Story 9.1) ([#90](https://github.com/jlengelbrecht/GlycemicGPT/issues/90)) ([35a5bfe](https://github.com/jlengelbrecht/GlycemicGPT/commit/35a5bfe24bc553e4b0e72919353108ad24f5f992))
* add Telegram bot setup and configuration (Story 7.1) ([#62](https://github.com/jlengelbrecht/GlycemicGPT/issues/62)) ([26b27b9](https://github.com/jlengelbrecht/GlycemicGPT/commit/26b27b934e4536c95ba399b2e1601b8bdad7198b))
* add Telegram bot token configuration with validation flow (Story 12.3) ([#115](https://github.com/jlengelbrecht/GlycemicGPT/issues/115)) ([429ed25](https://github.com/jlengelbrecht/GlycemicGPT/commit/429ed2543bfdd653dabadfb57edf9e370f1e0af0))
* add tiered alert delivery with real-time notifications (Story 6.3) ([#52](https://github.com/jlengelbrecht/GlycemicGPT/issues/52)) ([8a0463d](https://github.com/jlengelbrecht/GlycemicGPT/commit/8a0463d6a7c8cf4f931788f216da25fdf8ece2eb))
* add Wear OS watch face, alerts, and AI voice chat (Story 16.9) ([#189](https://github.com/jlengelbrecht/GlycemicGPT/issues/189)) ([12544ba](https://github.com/jlengelbrecht/GlycemicGPT/commit/12544ba56f2728f759cd6f6b93756ecc0ef63318))
* add web-based AI chat interface with backend endpoint (Story 11.2) ([#119](https://github.com/jlengelbrecht/GlycemicGPT/issues/119)) ([b73db9b](https://github.com/jlengelbrecht/GlycemicGPT/commit/b73db9b27f2fac6e242f4dc3ba3af58a3e11ac8b))
* Android mobile app scaffolding with BLE pump connectivity (Epic 16, Story 16.1) ([#168](https://github.com/jlengelbrecht/GlycemicGPT/issues/168)) ([0646f87](https://github.com/jlengelbrecht/GlycemicGPT/commit/0646f879c146bdf4611d94c9f771f8f7ea7a16b6))
* **api:** add AI chat via Telegram (Story 7.5) ([#75](https://github.com/jlengelbrecht/GlycemicGPT/issues/75)) ([fbf842d](https://github.com/jlengelbrecht/GlycemicGPT/commit/fbf842df3954e430db5b2e665fcd6bf65c1c48d7))
* **api:** add AI provider configuration (Story 5.1) ([#32](https://github.com/jlengelbrecht/GlycemicGPT/issues/32)) ([4cd3cb3](https://github.com/jlengelbrecht/GlycemicGPT/commit/4cd3cb32e22c96d6b4fd16622ebff8f846f75ef2))
* **api:** add BYOAI abstraction layer (Story 5.2) ([#34](https://github.com/jlengelbrecht/GlycemicGPT/issues/34)) ([ab23f76](https://github.com/jlengelbrecht/GlycemicGPT/commit/ab23f768ad6e69ee88565e0b32978502f27fe53a))
* **api:** add caregiver Telegram access (Story 7.6) ([#77](https://github.com/jlengelbrecht/GlycemicGPT/issues/77)) ([ef03858](https://github.com/jlengelbrecht/GlycemicGPT/commit/ef038584779e0c65b3542e170dcdd6de7976508c))
* **api:** add Control-IQ activity parsing and aggregation ([ce6ebb8](https://github.com/jlengelbrecht/GlycemicGPT/commit/ce6ebb85c6cbbea9ab3bbbabc9c8d351e7083411))
* **api:** add correction factor analysis with ISF suggestions (Story 5.5) ([#40](https://github.com/jlengelbrecht/GlycemicGPT/issues/40)) ([f7465ff](https://github.com/jlengelbrecht/GlycemicGPT/commit/f7465ff78ed43ba74f5737dbcade978a6ac9372f))
* **api:** add daily brief generation (Story 5.3) ([#36](https://github.com/jlengelbrecht/GlycemicGPT/issues/36)) ([209cfc3](https://github.com/jlengelbrecht/GlycemicGPT/commit/209cfc3b259896c3e54204bc82b1b77113ccb5fe))
* **api:** add IoB projection engine with decay curve ([#1](https://github.com/jlengelbrecht/GlycemicGPT/issues/1)) ([ab1b533](https://github.com/jlengelbrecht/GlycemicGPT/commit/ab1b5336ead73f101bec47510f9ffc40721cc85f))
* **api:** add meal pattern analysis with carb ratio suggestions (Story 5.4) ([#38](https://github.com/jlengelbrecht/GlycemicGPT/issues/38)) ([6d7d2fb](https://github.com/jlengelbrecht/GlycemicGPT/commit/6d7d2fb55dad04ed082e0ce6d8ee33909eff0592))
* **api:** add pre-validation safety layer for AI suggestions (Story 5.6) ([#42](https://github.com/jlengelbrecht/GlycemicGPT/issues/42)) ([c78650c](https://github.com/jlengelbrecht/GlycemicGPT/commit/c78650c77c1533c534487da459d47277adaa9f3b))
* **api:** add Telegram alert delivery for glucose alerts (Story 7.2) ([#64](https://github.com/jlengelbrecht/GlycemicGPT/issues/64)) ([117641f](https://github.com/jlengelbrecht/GlycemicGPT/commit/117641fbd417543f9a2c5ef1354065d6e8992a7b))
* **api:** add Telegram command handlers (Story 7.4) ([#68](https://github.com/jlengelbrecht/GlycemicGPT/issues/68)) ([b848004](https://github.com/jlengelbrecht/GlycemicGPT/commit/b848004b7f12fee11af09c35cd9e4f570934d620))
* **api:** deliver daily briefs via Telegram (Story 7.3) ([#66](https://github.com/jlengelbrecht/GlycemicGPT/issues/66)) ([f03ff51](https://github.com/jlengelbrecht/GlycemicGPT/commit/f03ff5120f308ed873523a76115c253655bbc43d))
* backend sync -- push real-time pump data to API (Story 16.5) ([#175](https://github.com/jlengelbrecht/GlycemicGPT/issues/175)) ([d6ed3a8](https://github.com/jlengelbrecht/GlycemicGPT/commit/d6ed3a8a85e195a86a6e339dad4e11eeb381f5ea))
* BLE connection manager and pump pairing (Story 16.2) ([#169](https://github.com/jlengelbrecht/GlycemicGPT/issues/169)) ([012db79](https://github.com/jlengelbrecht/GlycemicGPT/commit/012db7974f5166cedd2674bb08875d158799c5c1))
* BLE debug instrumentation, dev environment, and connection stability ([#204](https://github.com/jlengelbrecht/GlycemicGPT/issues/204)) ([c217be8](https://github.com/jlengelbrecht/GlycemicGPT/commit/c217be8d901a3e9d132a2ae45343fa02b47fde97))
* complete home screen dashboard with CGM, freshness, pull-to-refresh (Story 16.7) ([#181](https://github.com/jlengelbrecht/GlycemicGPT/issues/181)) ([5d8cf1e](https://github.com/jlengelbrecht/GlycemicGPT/commit/5d8cf1e961a730c8da9a0ceea18b82f04be043c6))
* enforce caregiver read-only access (Story 8.6) ([#88](https://github.com/jlengelbrecht/GlycemicGPT/issues/88)) ([f22db0d](https://github.com/jlengelbrecht/GlycemicGPT/commit/f22db0d67912726f04b926d3b25460de2287ac93))
* enhance AI Chat with comprehensive pump data context (Story 15.7) ([#161](https://github.com/jlengelbrecht/GlycemicGPT/issues/161)) ([093bb16](https://github.com/jlengelbrecht/GlycemicGPT/commit/093bb1691f23a87dcc2f48ac172e805c5044bd7c))
* expand AI provider system to support subscriptions and self-hosted models (Epic 14) ([#128](https://github.com/jlengelbrecht/GlycemicGPT/issues/128)) ([2b17e58](https://github.com/jlengelbrecht/GlycemicGPT/commit/2b17e5810dd8858e4454ee54be80a61619674756))
* glucose trend chart, IoB pipeline fix, and insulin settings ([#145](https://github.com/jlengelbrecht/GlycemicGPT/issues/145)) ([f0603e9](https://github.com/jlengelbrecht/GlycemicGPT/commit/f0603e9552104d5fe2333b442d0101e708d8ca6f))
* implement AI Chat screen in mobile app ([#214](https://github.com/jlengelbrecht/GlycemicGPT/issues/214)) ([582976d](https://github.com/jlengelbrecht/GlycemicGPT/commit/582976dc4d24cd7c0f5611d83ba9622c88c94076))
* implement app settings and configuration (Story 16.8) ([#185](https://github.com/jlengelbrecht/GlycemicGPT/issues/185)) ([235ae6b](https://github.com/jlengelbrecht/GlycemicGPT/commit/235ae6b3b0a3053801f8d76470f264a817b16439))
* implement BLE history log download from Tandem pump ([#226](https://github.com/jlengelbrecht/GlycemicGPT/issues/226)) ([c7766de](https://github.com/jlengelbrecht/GlycemicGPT/commit/c7766de98bd4e8d696af994cc5fa1351cb5bad90))
* implement caregiver and emergency contact push notifications (Story 16.11) ([#192](https://github.com/jlengelbrecht/GlycemicGPT/issues/192)) ([e009682](https://github.com/jlengelbrecht/GlycemicGPT/commit/e009682fe2203893248fa744d8ce3ab9af773767))
* implement PumpDriver status reads and live HomeScreen (Story 16.3) ([#170](https://github.com/jlengelbrecht/GlycemicGPT/issues/170)) ([3b63ffa](https://github.com/jlengelbrecht/GlycemicGPT/commit/3b63ffafa46d55f6517f1efaed3279a34cc0cba4))
* implement Tandem cloud upload pipeline (Story 16.6) ([#179](https://github.com/jlengelbrecht/GlycemicGPT/issues/179)) ([2509da6](https://github.com/jlengelbrecht/GlycemicGPT/commit/2509da615f24b67aaaf29756f7a1dd484f3e3d7d))
* move Tandem cloud upload settings from mobile to web integrations page ([#222](https://github.com/jlengelbrecht/GlycemicGPT/issues/222)) ([041fa22](https://github.com/jlengelbrecht/GlycemicGPT/commit/041fa229383d91b207f31de62e45579324b7a69f))
* polish landing page auth navigation and invite page links (Story 15.6) ([#140](https://github.com/jlengelbrecht/GlycemicGPT/issues/140)) ([aef753f](https://github.com/jlengelbrecht/GlycemicGPT/commit/aef753f24f3161ab2c434ea063bbe846b784fcc0))
* refactor AI provider backend for sidecar auto-routing (Story 15.4) ([#155](https://github.com/jlengelbrecht/GlycemicGPT/issues/155)) ([add9a69](https://github.com/jlengelbrecht/GlycemicGPT/commit/add9a69b4778af2a6d5a63f44091f87719d093b4))
* refactor AI provider frontend for sidecar subscription UX (Story 15.5) ([#157](https://github.com/jlengelbrecht/GlycemicGPT/issues/157)) ([abb1606](https://github.com/jlengelbrecht/GlycemicGPT/commit/abb16063f750a675950e036671c304af6bbf222e))
* replace mock Time in Range data with real API aggregation ([#213](https://github.com/jlengelbrecht/GlycemicGPT/issues/213)) ([479f131](https://github.com/jlengelbrecht/GlycemicGPT/commit/479f131c267bb86141bd62c44982ba8594e25c42))
* sidecar token-paste auth flow for subscription providers (Story 15.2) ([#149](https://github.com/jlengelbrecht/GlycemicGPT/issues/149)) ([829f9af](https://github.com/jlengelbrecht/GlycemicGPT/commit/829f9af66ba47d90ae9ff69687f6cf54dc6da626))
* sync pump settings profiles from Tandem API (Story 15.8) ([#163](https://github.com/jlengelbrecht/GlycemicGPT/issues/163)) ([1c46322](https://github.com/jlengelbrecht/GlycemicGPT/commit/1c46322601dec9e45545daa8c802bda075248feb))
* **web:** add AlertCard component with acknowledgment (Story 6.4) ([#54](https://github.com/jlengelbrecht/GlycemicGPT/issues/54)) ([2c9935b](https://github.com/jlengelbrecht/GlycemicGPT/commit/2c9935bf2c180feeaae9c7f02d03418da5c609b8))
* **web:** add dashboard accessibility and branding (Story 4.6) ([#28](https://github.com/jlengelbrecht/GlycemicGPT/issues/28)) ([67058e5](https://github.com/jlengelbrecht/GlycemicGPT/commit/67058e532dceefdd27b04ffad8301e7314020a5e))
* **web:** add dashboard layout and navigation ([#3](https://github.com/jlengelbrecht/GlycemicGPT/issues/3)) ([43b1659](https://github.com/jlengelbrecht/GlycemicGPT/commit/43b1659cc052f0414d2dcef895685c708b7fa6c3))
* **web:** add data freshness indicator component ([5556a03](https://github.com/jlengelbrecht/GlycemicGPT/commit/5556a036a041cc23ddb346a77e38fda45077197b))
* **web:** add GlucoseHero component for dashboard ([#20](https://github.com/jlengelbrecht/GlycemicGPT/issues/20)) ([52e8873](https://github.com/jlengelbrecht/GlycemicGPT/commit/52e88738fe6b3000091fe87e18be5e60e3ac6076))
* **web:** add multi-patient card grid for caregiver dashboard (Story 8.5) ([#86](https://github.com/jlengelbrecht/GlycemicGPT/issues/86)) ([9d08089](https://github.com/jlengelbrecht/GlycemicGPT/commit/9d0808917a41f785dc92476247564da2e00727b0))
* **web:** add TimeInRangeBar component for dashboard ([#24](https://github.com/jlengelbrecht/GlycemicGPT/issues/24)) ([e9f61f7](https://github.com/jlengelbrecht/GlycemicGPT/commit/e9f61f7a7b9cf71d98b8ab6c937264dac011e7a1))
* **web:** add TrendArrow component for reusable trend display ([#22](https://github.com/jlengelbrecht/GlycemicGPT/issues/22)) ([cc765d4](https://github.com/jlengelbrecht/GlycemicGPT/commit/cc765d40fc3bc975e568afd4a618cc7d8063d3cb))
* wire daily briefs web delivery with unread badge and filter tabs (Story 11.3) ([#121](https://github.com/jlengelbrecht/GlycemicGPT/issues/121)) ([1439b69](https://github.com/jlengelbrecht/GlycemicGPT/commit/1439b696babe65849143a2449b7d4493399104ff))


### 🐛 Bug Fixes

* add BLE runtime permission requests to prevent pump scan crash ([#198](https://github.com/jlengelbrecht/GlycemicGPT/issues/198)) ([56252bb](https://github.com/jlengelbrecht/GlycemicGPT/commit/56252bb783e66eb8aeaec42e38b9ac4ca6c7966c))
* add R8 keep rule for Tink errorprone annotations and OptIn for ExperimentalCoroutinesApi ([#177](https://github.com/jlengelbrecht/GlycemicGPT/issues/177)) ([965dd18](https://github.com/jlengelbrecht/GlycemicGPT/commit/965dd187401755ce46994bfd8ce4e6916c122258))
* BLE background persistence, sync reliability, and AI chat timeout ([#219](https://github.com/jlengelbrecht/GlycemicGPT/issues/219)) ([c170cbc](https://github.com/jlengelbrecht/GlycemicGPT/commit/c170cbc9a690bbae4445fd5ce1df7c110a8889e9))
* BLE reconnection stability -- prevent sync loss when phone idles ([#228](https://github.com/jlengelbrecht/GlycemicGPT/issues/228)) ([23ee57b](https://github.com/jlengelbrecht/GlycemicGPT/commit/23ee57b2f0ae111a3a40874d0dbce2c89c795df5))
* **ci:** resolve workflow failures for renovate, release, and auto-label ([#4](https://github.com/jlengelbrecht/GlycemicGPT/issues/4)) ([f15f19b](https://github.com/jlengelbrecht/GlycemicGPT/commit/f15f19b8aba5ac599e3fad0fec131cf49e44b3d6))
* **ci:** skip self-approval for release PR auto-merge ([#8](https://github.com/jlengelbrecht/GlycemicGPT/issues/8)) ([becc3e4](https://github.com/jlengelbrecht/GlycemicGPT/commit/becc3e499de444c91831a280eb2d084a640406d8))
* **ci:** use homebot.0 for release PR and enable auto-merge ([#6](https://github.com/jlengelbrecht/GlycemicGPT/issues/6)) ([ccd5ca2](https://github.com/jlengelbrecht/GlycemicGPT/commit/ccd5ca2b9782b094c8a0bb523dded1c14ea3f6e2))
* **ci:** use homebot.0 for Renovate to enable dependency dashboard ([#10](https://github.com/jlengelbrecht/GlycemicGPT/issues/10)) ([d54d084](https://github.com/jlengelbrecht/GlycemicGPT/commit/d54d084f2e5f1f20e6855498e24c7a598bb7b55f))
* convert carbRatio from milliunits in Tandem pump profile sync ([#165](https://github.com/jlengelbrecht/GlycemicGPT/issues/165)) ([fc5ea61](https://github.com/jlengelbrecht/GlycemicGPT/commit/fc5ea61bf7d8b9b183ecdde99c1323da3696c348))
* correct BLE authentication protocol to match Tandem pump spec ([#200](https://github.com/jlengelbrecht/GlycemicGPT/issues/200)) ([b578154](https://github.com/jlengelbrecht/GlycemicGPT/commit/b578154d05b5d982f2e8252ee1035d07a9f21dab))
* correct BLE status response opcodes and parser byte layouts ([#206](https://github.com/jlengelbrecht/GlycemicGPT/issues/206)) ([fd34f11](https://github.com/jlengelbrecht/GlycemicGPT/commit/fd34f11a85cb29a32ca58578eb227acdb1c825f2))
* correct CGM and bolus timestamp timezone conversion ([#209](https://github.com/jlengelbrecht/GlycemicGPT/issues/209)) ([977456d](https://github.com/jlengelbrecht/GlycemicGPT/commit/977456d2cffcc3a3a5a7dc506f369023cac1e026))
* correct Tandem cloud upload authentication to use tconnectsync's camelCase attributes ([#224](https://github.com/jlengelbrecht/GlycemicGPT/issues/224)) ([aea8749](https://github.com/jlengelbrecht/GlycemicGPT/commit/aea87494fd5e89bfafd8b2ae90252032e22d5092))
* correct trend arrow mapping and deployment config ([#142](https://github.com/jlengelbrecht/GlycemicGPT/issues/142)) ([9c05ef0](https://github.com/jlengelbrecht/GlycemicGPT/commit/9c05ef029c37a71aaa39020a04fdba35675876ea))
* display IoB with full 2-decimal precision on web dashboard ([#207](https://github.com/jlengelbrecht/GlycemicGPT/issues/207)) ([479059a](https://github.com/jlengelbrecht/GlycemicGPT/commit/479059a1e07662f1cf4b12ee125f83ef112273a4))
* enable Save Changes button when API is unavailable (Story 10.1) ([#100](https://github.com/jlengelbrecht/GlycemicGPT/issues/100)) ([c90fb69](https://github.com/jlengelbrecht/GlycemicGPT/commit/c90fb6936ec16b192b9264becdd4ef301770f86c))
* faster battery/reservoir polling and BLE connection stability ([#221](https://github.com/jlengelbrecht/GlycemicGPT/issues/221)) ([6ecc33d](https://github.com/jlengelbrecht/GlycemicGPT/commit/6ecc33df1a87f6a201d01ed3ee4a419e156446e0))
* implement EC-JPAKE authentication for Tandem pump BLE pairing ([#202](https://github.com/jlengelbrecht/GlycemicGPT/issues/202)) ([892d1a7](https://github.com/jlengelbrecht/GlycemicGPT/commit/892d1a796631da3a3c126bb6e8f6ef4d07f55f51))
* install Claude/Codex CLIs in sidecar and fix CLI invocation flags ([#159](https://github.com/jlengelbrecht/GlycemicGPT/issues/159)) ([34f7912](https://github.com/jlengelbrecht/GlycemicGPT/commit/34f7912171a908558b3cb5c9c3edc12b7e440d10))
* prevent cleartext requests to localhost when server URL not configured ([#196](https://github.com/jlengelbrecht/GlycemicGPT/issues/196)) ([d7e14b0](https://github.com/jlengelbrecht/GlycemicGPT/commit/d7e14b0a12a88076be30624f621563556885a49e))
* remove CLAUDE.md and _bmad-output from repo ([#183](https://github.com/jlengelbrecht/GlycemicGPT/issues/183)) ([ccc4a43](https://github.com/jlengelbrecht/GlycemicGPT/commit/ccc4a43f18d6608559c137b7e32513621da939d4))
* resolve release workflow YAML parse error on secrets in if-condition ([#171](https://github.com/jlengelbrecht/GlycemicGPT/issues/171)) ([05dbbe9](https://github.com/jlengelbrecht/GlycemicGPT/commit/05dbbe98900fbe29d834c416b426a03104b979a9))
* resolve web app cross-origin cookie and redirect loop bugs ([#211](https://github.com/jlengelbrecht/GlycemicGPT/issues/211)) ([c6c750f](https://github.com/jlengelbrecht/GlycemicGPT/commit/c6c750f1faa75ea6daacd1a9c5a775d2572caca9))
* use correct BLE opcode for pump hardware info parsing ([#223](https://github.com/jlengelbrecht/GlycemicGPT/issues/223)) ([7c840b8](https://github.com/jlengelbrecht/GlycemicGPT/commit/7c840b8955cb8afdb071e85966243183eb087f20))
* use hybrid dose-summation for accurate IoB projection ([#166](https://github.com/jlengelbrecht/GlycemicGPT/issues/166)) ([dd05690](https://github.com/jlengelbrecht/GlycemicGPT/commit/dd056905288397ddde8cb01c4e1adc947f93c27f))


### 📚 Documentation

* fix license and add development status banner ([#30](https://github.com/jlengelbrecht/GlycemicGPT/issues/30)) ([94ea95e](https://github.com/jlengelbrecht/GlycemicGPT/commit/94ea95e7e2f6996fb02b1ca49e356c3fd19940c1))


### 👷 CI/CD

* add CI/CD infrastructure and release automation ([#2](https://github.com/jlengelbrecht/GlycemicGPT/issues/2)) ([5c91a85](https://github.com/jlengelbrecht/GlycemicGPT/commit/5c91a85c4f21fb59cc55ef7449f4d51767b84e78))
* **autolabeler:** enhance PR labeling with JSON config and template parsing ([#14](https://github.com/jlengelbrecht/GlycemicGPT/issues/14)) ([adc3ee3](https://github.com/jlengelbrecht/GlycemicGPT/commit/adc3ee3c710280d0ad4507d40f5c738a5a6322ca))
* **docker:** add container build and push workflow for ghcr.io ([#16](https://github.com/jlengelbrecht/GlycemicGPT/issues/16)) ([7c60ae4](https://github.com/jlengelbrecht/GlycemicGPT/commit/7c60ae499588dbfc31c75b1a98b128b66d38f389))
* **docker:** add release notes update and image cleanup ([#18](https://github.com/jlengelbrecht/GlycemicGPT/issues/18)) ([71b46f1](https://github.com/jlengelbrecht/GlycemicGPT/commit/71b46f1012ce94b7142bee9ebe0426c2742e9978))

## [0.1.94](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.93...v0.1.94) (2026-02-16)


### ✨ Features

* replace mock Time in Range data with real API aggregation ([#213](https://github.com/jlengelbrecht/GlycemicGPT/issues/213)) ([3c4da3d](https://github.com/jlengelbrecht/GlycemicGPT/commit/3c4da3d4a517112ade806aaff51344b2e5baef23))

## [0.1.93](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.92...v0.1.93) (2026-02-16)


### 🐛 Bug Fixes

* resolve web app cross-origin cookie and redirect loop bugs ([#211](https://github.com/jlengelbrecht/GlycemicGPT/issues/211)) ([d88c799](https://github.com/jlengelbrecht/GlycemicGPT/commit/d88c79975d7ac529dcc710e05313fc6a75d61ac4))

## [0.1.92](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.91...v0.1.92) (2026-02-16)


### 🐛 Bug Fixes

* correct CGM and bolus timestamp timezone conversion ([#209](https://github.com/jlengelbrecht/GlycemicGPT/issues/209)) ([ba13da6](https://github.com/jlengelbrecht/GlycemicGPT/commit/ba13da672bd6de7de82dbb43d6a511457fce45c9))

## [0.1.91](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.90...v0.1.91) (2026-02-16)


### 🐛 Bug Fixes

* correct BLE status response opcodes and parser byte layouts ([#206](https://github.com/jlengelbrecht/GlycemicGPT/issues/206)) ([3de403d](https://github.com/jlengelbrecht/GlycemicGPT/commit/3de403dce99f9bbafeb4f8c4f72cf0db3b4a3d03))

## [0.1.90](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.89...v0.1.90) (2026-02-15)


### ✨ Features

* BLE debug instrumentation, dev environment, and connection stability ([#204](https://github.com/jlengelbrecht/GlycemicGPT/issues/204)) ([43f708f](https://github.com/jlengelbrecht/GlycemicGPT/commit/43f708fb1b732600e45ce74d9eebe9c64c204fa2))

## [0.1.89](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.88...v0.1.89) (2026-02-14)


### 🐛 Bug Fixes

* implement EC-JPAKE authentication for Tandem pump BLE pairing ([#202](https://github.com/jlengelbrecht/GlycemicGPT/issues/202)) ([0d89841](https://github.com/jlengelbrecht/GlycemicGPT/commit/0d89841ec5fdf65210e8f506e90f4004ea4b9704))

## [0.1.88](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.87...v0.1.88) (2026-02-14)


### 🐛 Bug Fixes

* correct BLE authentication protocol to match Tandem pump spec ([#200](https://github.com/jlengelbrecht/GlycemicGPT/issues/200)) ([9c8fb40](https://github.com/jlengelbrecht/GlycemicGPT/commit/9c8fb40d5c77d7132de107957259cd2752b29c25))

## [0.1.87](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.86...v0.1.87) (2026-02-14)


### 🐛 Bug Fixes

* add BLE runtime permission requests to prevent pump scan crash ([#198](https://github.com/jlengelbrecht/GlycemicGPT/issues/198)) ([bbc00cd](https://github.com/jlengelbrecht/GlycemicGPT/commit/bbc00cdc5b32444782a0ba1fce1dbbb635b7da52))

## [0.1.86](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.85...v0.1.86) (2026-02-14)


### 🐛 Bug Fixes

* prevent cleartext requests to localhost when server URL not configured ([#196](https://github.com/jlengelbrecht/GlycemicGPT/issues/196)) ([e861d64](https://github.com/jlengelbrecht/GlycemicGPT/commit/e861d646801642c8f9d441f6d9182c6f05af0082))

## [0.1.85](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.84...v0.1.85) (2026-02-14)


### ✨ Features

* add security hardening with token refresh, rate limiting, and TLS (Story 16.12) ([#194](https://github.com/jlengelbrecht/GlycemicGPT/issues/194)) ([4c6e15e](https://github.com/jlengelbrecht/GlycemicGPT/commit/4c6e15e90f455f0a9be82a1ba8cff56e8c546672))

## [0.1.84](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.83...v0.1.84) (2026-02-14)


### ✨ Features

* implement caregiver and emergency contact push notifications (Story 16.11) ([#192](https://github.com/jlengelbrecht/GlycemicGPT/issues/192)) ([78dfa10](https://github.com/jlengelbrecht/GlycemicGPT/commit/78dfa104d6f3b264ca9c2e1c0870636f881a2592))

## [0.1.83](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.82...v0.1.83) (2026-02-13)


### ✨ Features

* add Wear OS watch face, alerts, and AI voice chat (Story 16.9) ([#189](https://github.com/jlengelbrecht/GlycemicGPT/issues/189)) ([08f9c18](https://github.com/jlengelbrecht/GlycemicGPT/commit/08f9c18a0ad19eeed21200a17fbe841a9781072f))

## [0.1.82](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.81...v0.1.82) (2026-02-13)


### ✨ Features

* add GitHub self-update mechanism (Story 16.13) ([#187](https://github.com/jlengelbrecht/GlycemicGPT/issues/187)) ([ec0d369](https://github.com/jlengelbrecht/GlycemicGPT/commit/ec0d369428ec9acb796bfec5bbc9f6f28b76a4c0))

## [0.1.81](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.80...v0.1.81) (2026-02-13)


### ✨ Features

* implement app settings and configuration (Story 16.8) ([#185](https://github.com/jlengelbrecht/GlycemicGPT/issues/185)) ([31d31fc](https://github.com/jlengelbrecht/GlycemicGPT/commit/31d31fc8636b5046e90e375947a96e01d5b50f4d))

## [0.1.80](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.79...v0.1.80) (2026-02-13)


### 🐛 Bug Fixes

* remove CLAUDE.md and _bmad-output from repo ([#183](https://github.com/jlengelbrecht/GlycemicGPT/issues/183)) ([6b6c0a1](https://github.com/jlengelbrecht/GlycemicGPT/commit/6b6c0a1bf20b059b36dcdf1028ad52c67c4dcc98))

## [0.1.79](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.78...v0.1.79) (2026-02-13)


### ✨ Features

* complete home screen dashboard with CGM, freshness, pull-to-refresh (Story 16.7) ([#181](https://github.com/jlengelbrecht/GlycemicGPT/issues/181)) ([abd7d17](https://github.com/jlengelbrecht/GlycemicGPT/commit/abd7d17b652e536fd913103632f0543c548ba6f4))

## [0.1.78](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.77...v0.1.78) (2026-02-13)


### ✨ Features

* implement Tandem cloud upload pipeline (Story 16.6) ([#179](https://github.com/jlengelbrecht/GlycemicGPT/issues/179)) ([a36133b](https://github.com/jlengelbrecht/GlycemicGPT/commit/a36133bc9782f89b2f0fac32c0dc519a95db3aea))

## [0.1.77](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.76...v0.1.77) (2026-02-13)


### 🐛 Bug Fixes

* add R8 keep rule for Tink errorprone annotations and OptIn for ExperimentalCoroutinesApi ([#177](https://github.com/jlengelbrecht/GlycemicGPT/issues/177)) ([1e6dedb](https://github.com/jlengelbrecht/GlycemicGPT/commit/1e6dedb24ef469640aeacbe34f4c6555f98aabf1))

## [0.1.76](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.75...v0.1.76) (2026-02-13)


### ✨ Features

* backend sync -- push real-time pump data to API (Story 16.5) ([#175](https://github.com/jlengelbrecht/GlycemicGPT/issues/175)) ([f24f980](https://github.com/jlengelbrecht/GlycemicGPT/commit/f24f980115a39894b77d640321667bf170197ea6))

## [0.1.75](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.74...v0.1.75) (2026-02-13)


### ✨ Features

* add real-time data polling and local Room storage (Story 16.4) ([#173](https://github.com/jlengelbrecht/GlycemicGPT/issues/173)) ([e9f7c20](https://github.com/jlengelbrecht/GlycemicGPT/commit/e9f7c20229e6529d3afb84cdd523c084977e7719))

## [0.1.74](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.73...v0.1.74) (2026-02-13)


### ✨ Features

* Android mobile app scaffolding with BLE pump connectivity (Epic 16, Story 16.1) ([#168](https://github.com/jlengelbrecht/GlycemicGPT/issues/168)) ([3e5b1aa](https://github.com/jlengelbrecht/GlycemicGPT/commit/3e5b1aa5ddb1683fff9f8662d1f3e92849048435))
* BLE connection manager and pump pairing (Story 16.2) ([#169](https://github.com/jlengelbrecht/GlycemicGPT/issues/169)) ([9cb2432](https://github.com/jlengelbrecht/GlycemicGPT/commit/9cb24320d921d23320cd05925994a7e00134ccdd))
* implement PumpDriver status reads and live HomeScreen (Story 16.3) ([#170](https://github.com/jlengelbrecht/GlycemicGPT/issues/170)) ([ffab423](https://github.com/jlengelbrecht/GlycemicGPT/commit/ffab4238991fb8ce02d4395a4da671d4e465451c))


### 🐛 Bug Fixes

* resolve release workflow YAML parse error on secrets in if-condition ([#171](https://github.com/jlengelbrecht/GlycemicGPT/issues/171)) ([a6764c8](https://github.com/jlengelbrecht/GlycemicGPT/commit/a6764c831816df3c64278f44bbebea0f3add5297))

## [0.1.73](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.72...v0.1.73) (2026-02-12)


### 🐛 Bug Fixes

* convert carbRatio from milliunits in Tandem pump profile sync ([#165](https://github.com/jlengelbrecht/GlycemicGPT/issues/165)) ([8ee9677](https://github.com/jlengelbrecht/GlycemicGPT/commit/8ee9677286d02a6d4ef8fdbab96483a97b0e8579))
* use hybrid dose-summation for accurate IoB projection ([#166](https://github.com/jlengelbrecht/GlycemicGPT/issues/166)) ([1c2da35](https://github.com/jlengelbrecht/GlycemicGPT/commit/1c2da35587d17eac43c449e65ecff734d7eb16c8))

## [0.1.72](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.71...v0.1.72) (2026-02-12)


### ✨ Features

* sync pump settings profiles from Tandem API (Story 15.8) ([#163](https://github.com/jlengelbrecht/GlycemicGPT/issues/163)) ([f3a49a4](https://github.com/jlengelbrecht/GlycemicGPT/commit/f3a49a4027d7e8f6cd92b73b098d615c9840751f))

## [0.1.71](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.70...v0.1.71) (2026-02-12)


### ✨ Features

* enhance AI Chat with comprehensive pump data context (Story 15.7) ([#161](https://github.com/jlengelbrecht/GlycemicGPT/issues/161)) ([de10053](https://github.com/jlengelbrecht/GlycemicGPT/commit/de1005382af02d4037ab9f0264eda8b522f1bc09))

## [0.1.70](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.69...v0.1.70) (2026-02-12)


### 🐛 Bug Fixes

* install Claude/Codex CLIs in sidecar and fix CLI invocation flags ([#159](https://github.com/jlengelbrecht/GlycemicGPT/issues/159)) ([df88e01](https://github.com/jlengelbrecht/GlycemicGPT/commit/df88e01ed491762add29eedf5f9d4bdea2221ff7))

## [0.1.69](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.68...v0.1.69) (2026-02-12)


### ✨ Features

* refactor AI provider frontend for sidecar subscription UX (Story 15.5) ([#157](https://github.com/jlengelbrecht/GlycemicGPT/issues/157)) ([6e18f39](https://github.com/jlengelbrecht/GlycemicGPT/commit/6e18f391d046c2eba3a1f2657db8038d6fb791c9))

## [0.1.68](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.67...v0.1.68) (2026-02-12)


### ✨ Features

* refactor AI provider backend for sidecar auto-routing (Story 15.4) ([#155](https://github.com/jlengelbrecht/GlycemicGPT/issues/155)) ([2a8ccd9](https://github.com/jlengelbrecht/GlycemicGPT/commit/2a8ccd965f4c29d1c9f2fa8f67ac107d73dc91d3))

## [0.1.67](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.66...v0.1.67) (2026-02-12)


### ✨ Features

* add sidecar_provider column and make encrypted_api_key nullable (Story 15.7) ([#153](https://github.com/jlengelbrecht/GlycemicGPT/issues/153)) ([f223552](https://github.com/jlengelbrecht/GlycemicGPT/commit/f2235525371ead14826009e2393be8cc3171d501))

## [0.1.66](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.65...v0.1.66) (2026-02-12)


### ✨ Features

* add ai-sidecar to docker compose for all environments (Story 15.3) ([#151](https://github.com/jlengelbrecht/GlycemicGPT/issues/151)) ([b1fc695](https://github.com/jlengelbrecht/GlycemicGPT/commit/b1fc69591d33e77defee0b252dbecfcbb0b1146e))

## [0.1.65](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.64...v0.1.65) (2026-02-12)


### ✨ Features

* sidecar token-paste auth flow for subscription providers (Story 15.2) ([#149](https://github.com/jlengelbrecht/GlycemicGPT/issues/149)) ([4304818](https://github.com/jlengelbrecht/GlycemicGPT/commit/4304818a9fd2a193b2966bb7b98c507a2363f394))

## [0.1.64](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.63...v0.1.64) (2026-02-12)


### ✨ Features

* add AI sidecar container image (Story 15.1) ([#147](https://github.com/jlengelbrecht/GlycemicGPT/issues/147)) ([c3014df](https://github.com/jlengelbrecht/GlycemicGPT/commit/c3014df4ebe65ff8c621dff1fa81c29309a5af57))

## [0.1.63](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.62...v0.1.63) (2026-02-12)


### ✨ Features

* glucose trend chart, IoB pipeline fix, and insulin settings ([#145](https://github.com/jlengelbrecht/GlycemicGPT/issues/145)) ([5cdcbe6](https://github.com/jlengelbrecht/GlycemicGPT/commit/5cdcbe66cc2a92d100619930eff20b69f3fe6c50))

## [0.1.62](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.61...v0.1.62) (2026-02-11)


### 🐛 Bug Fixes

* correct trend arrow mapping and deployment config ([#142](https://github.com/jlengelbrecht/GlycemicGPT/issues/142)) ([e437661](https://github.com/jlengelbrecht/GlycemicGPT/commit/e437661eeb6da298bd7b69e5aacdae9306c0cd4f))

## [0.1.61](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.60...v0.1.61) (2026-02-11)


### ✨ Features

* polish landing page auth navigation and invite page links (Story 15.6) ([#140](https://github.com/jlengelbrecht/GlycemicGPT/issues/140)) ([fa6be0b](https://github.com/jlengelbrecht/GlycemicGPT/commit/fa6be0b86ef19ed078f6e8ef8fe72292304273e5))

## [0.1.60](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.59...v0.1.60) (2026-02-11)


### ✨ Features

* add post-login disclaimer enforcement (Story 15.5) ([#138](https://github.com/jlengelbrecht/GlycemicGPT/issues/138)) ([f12889d](https://github.com/jlengelbrecht/GlycemicGPT/commit/f12889d07348a5e8bdc969cd85a676adc5f8da0c))

## [0.1.59](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.58...v0.1.59) (2026-02-11)


### ✨ Features

* add logout, auth state display, and global 401 handling (Story 15.4) ([#136](https://github.com/jlengelbrecht/GlycemicGPT/issues/136)) ([92df866](https://github.com/jlengelbrecht/GlycemicGPT/commit/92df866f622c575d043c060d0f3d7f737c69fdb8))

## [0.1.58](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.57...v0.1.58) (2026-02-11)


### ✨ Features

* add auth middleware for route protection (Story 15.3) ([#134](https://github.com/jlengelbrecht/GlycemicGPT/issues/134)) ([bfb3a20](https://github.com/jlengelbrecht/GlycemicGPT/commit/bfb3a203ae3f43e9a803dd46bc3378c21dc63561))

## [0.1.57](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.56...v0.1.57) (2026-02-11)


### ✨ Features

* add registration page with password strength indicators (Story 15.2) ([#132](https://github.com/jlengelbrecht/GlycemicGPT/issues/132)) ([0194d67](https://github.com/jlengelbrecht/GlycemicGPT/commit/0194d672f897e4da3b4d490618086509f447c208))

## [0.1.56](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.55...v0.1.56) (2026-02-11)


### ✨ Features

* add login page with email/password authentication (Story 15.1) ([#130](https://github.com/jlengelbrecht/GlycemicGPT/issues/130)) ([cc8a23b](https://github.com/jlengelbrecht/GlycemicGPT/commit/cc8a23b8f0beabe4101fa713607857fb0c3432dd))

## [0.1.55](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.54...v0.1.55) (2026-02-11)


### ✨ Features

* expand AI provider system to support subscriptions and self-hosted models (Epic 14) ([#128](https://github.com/jlengelbrecht/GlycemicGPT/issues/128)) ([b01d790](https://github.com/jlengelbrecht/GlycemicGPT/commit/b01d79041953e19676433ba6cb36e8eeb018a42a))

## [0.1.54](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.53...v0.1.54) (2026-02-11)


### ✨ Features

* add Docker container integration testing (Story 13.2) ([#124](https://github.com/jlengelbrecht/GlycemicGPT/issues/124)) ([923b750](https://github.com/jlengelbrecht/GlycemicGPT/commit/923b7501c25747692b0a9bf621ac1723b053c6a7))

## [0.1.53](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.52...v0.1.53) (2026-02-11)


### ✨ Features

* add local dev server testing checklist and smoke tests (Story 13.1) ([#123](https://github.com/jlengelbrecht/GlycemicGPT/issues/123)) ([599efb1](https://github.com/jlengelbrecht/GlycemicGPT/commit/599efb18485fcbe8c8d6a6116d751ce89daef18f))

## [0.1.52](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.51...v0.1.52) (2026-02-11)


### ✨ Features

* wire daily briefs web delivery with unread badge and filter tabs (Story 11.3) ([#121](https://github.com/jlengelbrecht/GlycemicGPT/issues/121)) ([cf4da55](https://github.com/jlengelbrecht/GlycemicGPT/commit/cf4da55842747719191913d78e58d3c4f3dc7c2d))

## [0.1.51](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.50...v0.1.51) (2026-02-11)


### ✨ Features

* add web-based AI chat interface with backend endpoint (Story 11.2) ([#119](https://github.com/jlengelbrecht/GlycemicGPT/issues/119)) ([f071aa4](https://github.com/jlengelbrecht/GlycemicGPT/commit/f071aa4f85e2076711b271dabfa1b680b59ed2ad))

## [0.1.50](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.49...v0.1.50) (2026-02-11)


### ✨ Features

* add AI provider configuration page (Story 11.1) ([#117](https://github.com/jlengelbrecht/GlycemicGPT/issues/117)) ([92d85fd](https://github.com/jlengelbrecht/GlycemicGPT/commit/92d85fd5e1dea4dc9300d780bc325512b8a51013))

## [0.1.49](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.48...v0.1.49) (2026-02-11)


### ✨ Features

* add Telegram bot token configuration with validation flow (Story 12.3) ([#115](https://github.com/jlengelbrecht/GlycemicGPT/issues/115)) ([ddc6567](https://github.com/jlengelbrecht/GlycemicGPT/commit/ddc656752151e0b78f31d71e528a834a2c33d81d))

## [0.1.48](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.47...v0.1.48) (2026-02-11)


### ✨ Features

* add communications settings hub page (Story 12.2) ([#113](https://github.com/jlengelbrecht/GlycemicGPT/issues/113)) ([2b27ee5](https://github.com/jlengelbrecht/GlycemicGPT/commit/2b27ee551f82614826ccb1ec9783712095bdb0f4))

## [0.1.47](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.46...v0.1.47) (2026-02-11)


### ✨ Features

* add graceful offline/disconnected state to all settings pages (Story 12.4) ([#111](https://github.com/jlengelbrecht/GlycemicGPT/issues/111)) ([ba90090](https://github.com/jlengelbrecht/GlycemicGPT/commit/ba9009063b47edab00fe86a5877c56a9eae269ee))

## [0.1.46](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.45...v0.1.46) (2026-02-11)


### ✨ Features

* add integrations settings page for Dexcom and Tandem (Story 12.1) ([#109](https://github.com/jlengelbrecht/GlycemicGPT/issues/109)) ([36fbfec](https://github.com/jlengelbrecht/GlycemicGPT/commit/36fbfec2fa9388b4da4c4541bff3e3e8ec6fa8c0))

## [0.1.45](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.44...v0.1.45) (2026-02-11)


### ✨ Features

* add alert settings page for thresholds and escalation (Story 10.3) ([#107](https://github.com/jlengelbrecht/GlycemicGPT/issues/107)) ([12bb319](https://github.com/jlengelbrecht/GlycemicGPT/commit/12bb3193f6fd3c0b617679f4fd3575bb02885993))

## [0.1.44](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.43...v0.1.44) (2026-02-10)


### ✨ Features

* add profile settings page with display name and password change (Story 10.2) ([#105](https://github.com/jlengelbrecht/GlycemicGPT/issues/105)) ([5dccac1](https://github.com/jlengelbrecht/GlycemicGPT/commit/5dccac1a0533dfe72af3459b3d62ae2492eadd7d))

## [0.1.43](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.42...v0.1.43) (2026-02-10)


### 🐛 Bug Fixes

* enable Save Changes button when API is unavailable (Story 10.1) ([#100](https://github.com/jlengelbrecht/GlycemicGPT/issues/100)) ([854c9f4](https://github.com/jlengelbrecht/GlycemicGPT/commit/854c9f4dcdd51c7e6f4be7693200d92db3caa379))

## [0.1.42](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.41...v0.1.42) (2026-02-10)


### ✨ Features

* add settings export capability (Story 9.5) ([#98](https://github.com/jlengelbrecht/GlycemicGPT/issues/98)) ([bdd656b](https://github.com/jlengelbrecht/GlycemicGPT/commit/bdd656bc4910f696b5f77af6070eb1cfdea91fc0))

## [0.1.41](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.40...v0.1.41) (2026-02-10)


### ✨ Features

* add data purge capability (Story 9.4) ([#96](https://github.com/jlengelbrecht/GlycemicGPT/issues/96)) ([a1af404](https://github.com/jlengelbrecht/GlycemicGPT/commit/a1af404f14574e8e39a7aa1620f2b875a1193b0e))

## [0.1.40](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.39...v0.1.40) (2026-02-10)


### ✨ Features

* add data retention settings (Story 9.3) ([#94](https://github.com/jlengelbrecht/GlycemicGPT/issues/94)) ([86c9ce2](https://github.com/jlengelbrecht/GlycemicGPT/commit/86c9ce271a659a43b10407eb8cf09e99ab7fb4ec))

## [0.1.39](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.38...v0.1.39) (2026-02-10)


### ✨ Features

* add daily brief delivery configuration (Story 9.2) ([#92](https://github.com/jlengelbrecht/GlycemicGPT/issues/92)) ([5ab969c](https://github.com/jlengelbrecht/GlycemicGPT/commit/5ab969c2d11ef872798c48ce2f5ad141b987dc76))

## [0.1.38](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.37...v0.1.38) (2026-02-10)


### ✨ Features

* add target glucose range configuration (Story 9.1) ([#90](https://github.com/jlengelbrecht/GlycemicGPT/issues/90)) ([07473e1](https://github.com/jlengelbrecht/GlycemicGPT/commit/07473e16bdf4e2fc48f3c23a3834896665771bfd))

## [0.1.37](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.36...v0.1.37) (2026-02-10)


### ✨ Features

* enforce caregiver read-only access (Story 8.6) ([#88](https://github.com/jlengelbrecht/GlycemicGPT/issues/88)) ([85ef5b2](https://github.com/jlengelbrecht/GlycemicGPT/commit/85ef5b2688d24599dc13161a5ac4f55a9d27e5d5))

## [0.1.36](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.35...v0.1.36) (2026-02-10)


### ✨ Features

* **web:** add multi-patient card grid for caregiver dashboard (Story 8.5) ([#86](https://github.com/jlengelbrecht/GlycemicGPT/issues/86)) ([33dd43d](https://github.com/jlengelbrecht/GlycemicGPT/commit/33dd43d9b068d379d23ba3cd47cb93c240ffa584))

## [0.1.35](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.34...v0.1.35) (2026-02-10)


### ✨ Features

* add caregiver AI chat for patient queries (Story 8.4) ([#84](https://github.com/jlengelbrecht/GlycemicGPT/issues/84)) ([23f66d5](https://github.com/jlengelbrecht/GlycemicGPT/commit/23f66d56ff4b1b33db2bbdfbc6b9e2e54ba4287f))

## [0.1.34](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.33...v0.1.34) (2026-02-09)


### ✨ Features

* add caregiver dashboard view (Story 8.3) ([#82](https://github.com/jlengelbrecht/GlycemicGPT/issues/82)) ([e40bdae](https://github.com/jlengelbrecht/GlycemicGPT/commit/e40bdae3a4983bf5ea90bfac295fff11963aa1ca))

## [0.1.33](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.32...v0.1.33) (2026-02-09)


### ✨ Features

* add caregiver data access permission management (Story 8.2) ([#80](https://github.com/jlengelbrecht/GlycemicGPT/issues/80)) ([8813c3c](https://github.com/jlengelbrecht/GlycemicGPT/commit/8813c3ceca7aa572890f1808a139123d03e5eb48))

## [0.1.32](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.31...v0.1.32) (2026-02-09)


### ✨ Features

* add caregiver account creation and linking (Story 8.1) ([#78](https://github.com/jlengelbrecht/GlycemicGPT/issues/78)) ([ddbf068](https://github.com/jlengelbrecht/GlycemicGPT/commit/ddbf068859c3cee817e1457890d02e8afab6dd64))
* **api:** add caregiver Telegram access (Story 7.6) ([#77](https://github.com/jlengelbrecht/GlycemicGPT/issues/77)) ([cead938](https://github.com/jlengelbrecht/GlycemicGPT/commit/cead93821bdc9e09d8b4c482a2cd481f7c46335e))

## [0.1.31](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.30...v0.1.31) (2026-02-09)


### ✨ Features

* **api:** add AI chat via Telegram (Story 7.5) ([#75](https://github.com/jlengelbrecht/GlycemicGPT/issues/75)) ([1697b6b](https://github.com/jlengelbrecht/GlycemicGPT/commit/1697b6b1e89d3506532754f3f493220a3d80c6cf))

## [0.1.30](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.29...v0.1.30) (2026-02-09)


### ✨ Features

* **api:** add Telegram command handlers (Story 7.4) ([#68](https://github.com/jlengelbrecht/GlycemicGPT/issues/68)) ([d5b8be9](https://github.com/jlengelbrecht/GlycemicGPT/commit/d5b8be946625a3b8a1c570f1464b9d9a761d0f5a))

## [0.1.29](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.28...v0.1.29) (2026-02-09)


### ✨ Features

* **api:** deliver daily briefs via Telegram (Story 7.3) ([#66](https://github.com/jlengelbrecht/GlycemicGPT/issues/66)) ([bfe5622](https://github.com/jlengelbrecht/GlycemicGPT/commit/bfe5622f2e347414dd4de7d8bec69de34b9ad33e))

## [0.1.28](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.27...v0.1.28) (2026-02-09)


### ✨ Features

* **api:** add Telegram alert delivery for glucose alerts (Story 7.2) ([#64](https://github.com/jlengelbrecht/GlycemicGPT/issues/64)) ([426d736](https://github.com/jlengelbrecht/GlycemicGPT/commit/426d736608639f5728fb1d403e55b888c36ade49))

## [0.1.27](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.26...v0.1.27) (2026-02-09)


### ✨ Features

* add Telegram bot setup and configuration (Story 7.1) ([#62](https://github.com/jlengelbrecht/GlycemicGPT/issues/62)) ([64d6f98](https://github.com/jlengelbrecht/GlycemicGPT/commit/64d6f98feb2935488400eb429440ea8d675e9687))

## [0.1.26](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.25...v0.1.26) (2026-02-09)


### ✨ Features

* add automatic escalation to caregivers (Story 6.7) ([#60](https://github.com/jlengelbrecht/GlycemicGPT/issues/60)) ([50dd1f9](https://github.com/jlengelbrecht/GlycemicGPT/commit/50dd1f9f8e5979f029d2bd64fd62ac2236292586))

## [0.1.25](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.24...v0.1.25) (2026-02-09)


### ✨ Features

* add escalation timing configuration (Story 6.6) ([#58](https://github.com/jlengelbrecht/GlycemicGPT/issues/58)) ([a029bf9](https://github.com/jlengelbrecht/GlycemicGPT/commit/a029bf9b6f765afe4c758f9216dcccee9098ef28))

## [0.1.24](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.23...v0.1.24) (2026-02-09)


### ✨ Features

* add emergency contact configuration (Story 6.5) ([#56](https://github.com/jlengelbrecht/GlycemicGPT/issues/56)) ([c8f50c6](https://github.com/jlengelbrecht/GlycemicGPT/commit/c8f50c6c553a548c952acc2acddf89b5789a88df))

## [0.1.23](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.22...v0.1.23) (2026-02-09)


### ✨ Features

* **web:** add AlertCard component with acknowledgment (Story 6.4) ([#54](https://github.com/jlengelbrecht/GlycemicGPT/issues/54)) ([1e8b18f](https://github.com/jlengelbrecht/GlycemicGPT/commit/1e8b18fb9c0403bbc65d22f9d842a2f13c1b6201))

## [0.1.22](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.21...v0.1.22) (2026-02-09)


### ✨ Features

* add tiered alert delivery with real-time notifications (Story 6.3) ([#52](https://github.com/jlengelbrecht/GlycemicGPT/issues/52)) ([a83e945](https://github.com/jlengelbrecht/GlycemicGPT/commit/a83e945ec88ac8ddd05f245ac5d4ca736351178e))

## [0.1.21](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.20...v0.1.21) (2026-02-09)


### ✨ Features

* add predictive alert engine with IoB escalation (Story 6.2) ([#50](https://github.com/jlengelbrecht/GlycemicGPT/issues/50)) ([33d6525](https://github.com/jlengelbrecht/GlycemicGPT/commit/33d6525fa97b99bdbe6419008adabeea8df4a6fa))

## [0.1.20](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.19...v0.1.20) (2026-02-09)


### ✨ Features

* add alert threshold configuration (Story 6.1) ([#48](https://github.com/jlengelbrecht/GlycemicGPT/issues/48)) ([0ec59bb](https://github.com/jlengelbrecht/GlycemicGPT/commit/0ec59bbd952d21fca15e607e25f288a8fed9d1c3))

## [0.1.19](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.18...v0.1.19) (2026-02-09)


### ✨ Features

* add AI reasoning display and audit logging (Story 5.8) ([#46](https://github.com/jlengelbrecht/GlycemicGPT/issues/46)) ([a3b32b3](https://github.com/jlengelbrecht/GlycemicGPT/commit/a3b32b38ca149fa582e0f92ea490cc08e43a796e))

## [0.1.18](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.17...v0.1.18) (2026-02-09)


### ✨ Features

* add AI insight card and unified insights feed (Story 5.7) ([#44](https://github.com/jlengelbrecht/GlycemicGPT/issues/44)) ([1509fa2](https://github.com/jlengelbrecht/GlycemicGPT/commit/1509fa21eb39dfcb7c04b2e9f093b39674dd809b))

## [0.1.17](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.16...v0.1.17) (2026-02-08)


### ✨ Features

* **api:** add pre-validation safety layer for AI suggestions (Story 5.6) ([#42](https://github.com/jlengelbrecht/GlycemicGPT/issues/42)) ([a1aa06c](https://github.com/jlengelbrecht/GlycemicGPT/commit/a1aa06ca012124e4c976ba1a1139478737c20724))

## [0.1.16](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.15...v0.1.16) (2026-02-08)


### ✨ Features

* **api:** add correction factor analysis with ISF suggestions (Story 5.5) ([#40](https://github.com/jlengelbrecht/GlycemicGPT/issues/40)) ([7765de9](https://github.com/jlengelbrecht/GlycemicGPT/commit/7765de97391920611b62de89b2c04fc5824fe0a6))

## [0.1.15](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.14...v0.1.15) (2026-02-08)


### ✨ Features

* **api:** add meal pattern analysis with carb ratio suggestions (Story 5.4) ([#38](https://github.com/jlengelbrecht/GlycemicGPT/issues/38)) ([306dfbc](https://github.com/jlengelbrecht/GlycemicGPT/commit/306dfbc33ce0870655b2bd8280593e86108fb1a4))

## [0.1.14](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.13...v0.1.14) (2026-02-08)


### ✨ Features

* **api:** add daily brief generation (Story 5.3) ([#36](https://github.com/jlengelbrecht/GlycemicGPT/issues/36)) ([5d5b9ee](https://github.com/jlengelbrecht/GlycemicGPT/commit/5d5b9eee6d8a95e1269e50a17f27bb15a45cf0ad))

## [0.1.13](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.12...v0.1.13) (2026-02-08)


### ✨ Features

* **api:** add BYOAI abstraction layer (Story 5.2) ([#34](https://github.com/jlengelbrecht/GlycemicGPT/issues/34)) ([b87d9a7](https://github.com/jlengelbrecht/GlycemicGPT/commit/b87d9a7157908c06cb3e0c5a5a442af6dbebac14))

## [0.1.12](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.11...v0.1.12) (2026-02-08)


### ✨ Features

* **api:** add AI provider configuration (Story 5.1) ([#32](https://github.com/jlengelbrecht/GlycemicGPT/issues/32)) ([69ccdda](https://github.com/jlengelbrecht/GlycemicGPT/commit/69ccddaffcd54325f07a03d2d7f71e498ea8f5cd))

## [0.1.11](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.10...v0.1.11) (2026-02-08)


### 📚 Documentation

* fix license and add development status banner ([#30](https://github.com/jlengelbrecht/GlycemicGPT/issues/30)) ([ad18e8c](https://github.com/jlengelbrecht/GlycemicGPT/commit/ad18e8cf767aa179f6e52cefbcf7f7a3f112d652))

## [0.1.10](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.9...v0.1.10) (2026-02-08)


### ✨ Features

* **web:** add dashboard accessibility and branding (Story 4.6) ([#28](https://github.com/jlengelbrecht/GlycemicGPT/issues/28)) ([53651a8](https://github.com/jlengelbrecht/GlycemicGPT/commit/53651a89824fea1b290ec11cbc7f2a564b668b87))

## [0.1.9](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.8...v0.1.9) (2026-02-08)


### ✨ Features

* add real-time glucose updates via SSE (Story 4.5) ([#26](https://github.com/jlengelbrecht/GlycemicGPT/issues/26)) ([35e493d](https://github.com/jlengelbrecht/GlycemicGPT/commit/35e493dbe7d735d4ae16c3411b5232f58e1fde68))

## [0.1.8](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.7...v0.1.8) (2026-02-08)


### ✨ Features

* **web:** add TimeInRangeBar component for dashboard ([#24](https://github.com/jlengelbrecht/GlycemicGPT/issues/24)) ([075c9a7](https://github.com/jlengelbrecht/GlycemicGPT/commit/075c9a7d43d68b4e46b7b12821e37cd52bee0f7d))

## [0.1.7](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.6...v0.1.7) (2026-02-08)


### ✨ Features

* **web:** add TrendArrow component for reusable trend display ([#22](https://github.com/jlengelbrecht/GlycemicGPT/issues/22)) ([92af665](https://github.com/jlengelbrecht/GlycemicGPT/commit/92af665b0d96f0a9e105490a1d59e30133c66f0b))

## [0.1.6](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.5...v0.1.6) (2026-02-07)


### ✨ Features

* **web:** add GlucoseHero component for dashboard ([#20](https://github.com/jlengelbrecht/GlycemicGPT/issues/20)) ([1456e7f](https://github.com/jlengelbrecht/GlycemicGPT/commit/1456e7f5fae3bc7dd58c93c4a07b7752933df708))

## [0.1.5](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.4...v0.1.5) (2026-02-07)


### 👷 CI/CD

* **docker:** add release notes update and image cleanup ([#18](https://github.com/jlengelbrecht/GlycemicGPT/issues/18)) ([6066aac](https://github.com/jlengelbrecht/GlycemicGPT/commit/6066aac70cdef1db2c3fb5273d0159c7528d69af))

## [0.1.4](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.3...v0.1.4) (2026-02-07)


### 👷 CI/CD

* **docker:** add container build and push workflow for ghcr.io ([#16](https://github.com/jlengelbrecht/GlycemicGPT/issues/16)) ([d7d2dee](https://github.com/jlengelbrecht/GlycemicGPT/commit/d7d2dee75fe0f3c7212fce2d8dca079aa41a0fdd))

## [0.1.3](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.2...v0.1.3) (2026-02-07)


### 👷 CI/CD

* **autolabeler:** enhance PR labeling with JSON config and template parsing ([#14](https://github.com/jlengelbrecht/GlycemicGPT/issues/14)) ([750b432](https://github.com/jlengelbrecht/GlycemicGPT/commit/750b4329d232ad33676d4d8c36ba183ecd421e63))

## [0.1.2](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.1...v0.1.2) (2026-02-07)


### 🐛 Bug Fixes

* **ci:** use homebot.0 for Renovate to enable dependency dashboard ([#10](https://github.com/jlengelbrecht/GlycemicGPT/issues/10)) ([c935eef](https://github.com/jlengelbrecht/GlycemicGPT/commit/c935eef7a9cd35ff1f965fb8263dd27e729ad3b8))

## [0.1.1](https://github.com/jlengelbrecht/GlycemicGPT/compare/v0.1.0...v0.1.1) (2026-02-07)


### ✨ Features

* add FastAPI backend, Next.js frontend, and K8s deployment ([f2ae4b3](https://github.com/jlengelbrecht/GlycemicGPT/commit/f2ae4b3fc4424915acc447fe1d03ddc9ced02d95))
* **api:** add Control-IQ activity parsing and aggregation ([1b7f86f](https://github.com/jlengelbrecht/GlycemicGPT/commit/1b7f86f36dbc5451ade93a81b8d8a556d57544df))
* **api:** add IoB projection engine with decay curve ([#1](https://github.com/jlengelbrecht/GlycemicGPT/issues/1)) ([51ae57d](https://github.com/jlengelbrecht/GlycemicGPT/commit/51ae57dc3b43f394bd2dce2e6ea5da09d6ad59e9))
* **web:** add dashboard layout and navigation ([#3](https://github.com/jlengelbrecht/GlycemicGPT/issues/3)) ([0f1bec3](https://github.com/jlengelbrecht/GlycemicGPT/commit/0f1bec301224026eb75597a4e3289b93ab614364))
* **web:** add data freshness indicator component ([ff58074](https://github.com/jlengelbrecht/GlycemicGPT/commit/ff58074ce264a1ada627be6469f039d36e10cbd2))


### 🐛 Bug Fixes

* **ci:** resolve workflow failures for renovate, release, and auto-label ([#4](https://github.com/jlengelbrecht/GlycemicGPT/issues/4)) ([018fd47](https://github.com/jlengelbrecht/GlycemicGPT/commit/018fd47fae1d283f4e050ce61f0500890788cac6))
* **ci:** skip self-approval for release PR auto-merge ([#8](https://github.com/jlengelbrecht/GlycemicGPT/issues/8)) ([af8bda1](https://github.com/jlengelbrecht/GlycemicGPT/commit/af8bda15e314afb34b302bcfd62107e00e24003b))
* **ci:** use homebot.0 for release PR and enable auto-merge ([#6](https://github.com/jlengelbrecht/GlycemicGPT/issues/6)) ([229e8a9](https://github.com/jlengelbrecht/GlycemicGPT/commit/229e8a9cb2a936b83889c2c6626246b432792ff1))
