# Sponsors and Support

This document is the canonical record of GlycemicGPT's support relationships
(both in-kind and financial). README, GOVERNANCE.md, and `funding.json` may
reference these relationships at a summary level; this file is the source of
truth for details.

The project has no financial sponsors at this time.

## Active Sponsors

### <picture><source media="(prefers-color-scheme: dark)" srcset="assets/sponsors/1password-dark.svg"><img src="assets/sponsors/1password.svg" alt="" width="24" height="24" align="absmiddle"></picture> 1Password for Open Source

- **Type:** In-kind (donated software/services)
- **Started:** 2026-05-17
- **Will be used for:** team password management for project maintainers, with
  scoped access for contributors planned as the team grows. Specifically planned: a
  shared vault for third-party service and infrastructure credentials, secure handoff of the dev
  test account, and (later) CI integration via `1password/load-secrets-action`
  for secrets that benefit from centralized rotation.
- **Program:** <https://github.com/1Password/for-open-source>

### <picture><source media="(prefers-color-scheme: dark)" srcset="assets/sponsors/sentry-dark.svg"><img src="assets/sponsors/sentry.svg" alt="" width="24" height="24" align="absmiddle"></picture> Sentry for Good

- **Type:** In-kind (donated software/services)
- **Started:** 2026-05-20
- **Provides:** a sponsored open-source account on Sentry's Business plan, with
  no term limit. The current Open-Source Sponsorship Plan allotment is:
  - 5M errors
  - 5,000 GB logs
  - 1B tracing spans
  - 100K session replays
  - 500 cron monitors
  - 25 uptime monitors
  - 3,000 continuous profiling hours and 150 UI profiling hours
  - 10 GB attachments
  - 1,000 app size-analysis uploads
  - Seer (AI-assisted debugging) for 5 active contributors
  - Business-plan feature set; on-demand (paid overage) budget available

  The project uses only a subset of this grant (see below); the full allotment
  is recorded here for transparency about the value of the in-kind donation.
- **Will be used for:** error monitoring and observability for the project's own
  development, CI, and staging environments -- to capture and triage crashes
  before they reach a stable release. The project deliberately enables only the
  low-risk products that cannot carry user data: error monitoring, cron and
  uptime checks, and performance profiling. Session Replay, log ingestion, and
  event attachments are never enabled on any project-operated instance, and the
  on-demand paid budget is left disabled. No telemetry is collected from builds
  the project distributes: the Sentry DSN is supplied only via an environment
  variable in maintainer-controlled environments and is never baked into any
  published Docker image, web bundle, or APK -- production or `develop`.
  Self-hosters who want error monitoring may point their own Sentry DSN at their
  own deployment; that data goes to their account, not the project's. Production
  releases remain telemetry-free. See [PRIVACY.md](PRIVACY.md) for the full
  posture.
- **Program:** <https://sentry.io/for/good/>

## Fiscal Host

### <img src="assets/sponsors/opensource-collective.png" alt="" width="49" height="24" align="absmiddle"> Open Source Collective

- **Type:** Fiscal hosting (501(c)(6) nonprofit, US)
- **Status:** Active. GlycemicGPT is fiscally hosted by Open Source Collective;
  the collective went live before this document was created, so the exact
  hosting-start date is recorded on Open Collective rather than reproduced here.
- **Provides:** Fiscal hosting for GlycemicGPT, governance and compliance
  support, and payment processing for any donations received via Open
  Collective. The project's collective page is at
  <https://opencollective.com/glycemicgpt>; all project income, expenses, and
  balances are public by default. See
  [`GOVERNANCE.md` § What the fund covers](GOVERNANCE.md#what-the-fund-covers)
  for the full ledger model and how funds are used.

## Past Sponsors

_No past sponsorships at this time._

## Disclosure

GlycemicGPT does not currently receive financial sponsorship from any source.
The project has no operating revenue beyond what flows through Open Collective.

The 1Password for Open Source program, the Sentry for Good program, and Open
Source Collective hosting all carry baseline eligibility terms (open-source
status, non-commercial use, hosting agreement compliance, etc.). Within those
baseline terms, none of the sponsors nor the fiscal host exerts influence over
the project's technical direction, roadmap, or governance. Project decisions are
made by the project lead and maintainer team independently of sponsor or
fiscal-host input.

Sentry's involvement is limited to the project's own development, CI, and
staging environments. No build the project distributes -- production or
`develop` -- is configured to send error telemetry to the project's Sentry, and
self-hosted deployments operate entirely offline from sponsor infrastructure
unless the operator chooses to wire up their own Sentry account. Production
releases include no error telemetry of any kind. This is consistent with the
project's [Privacy-First principle](ROADMAP.md) and documented in full in
[PRIVACY.md](PRIVACY.md).

## Becoming a Sponsor

Interested in supporting GlycemicGPT?

- **Financial donations:** through our Open Collective page at
  <https://opencollective.com/glycemicgpt>.
- **In-kind support** (services, infrastructure, tooling): please email
  <funding@glycemicgpt.org>. Opening a public issue is also acceptable but
  email is preferred for relationships that may involve commercial terms,
  exclusivity, or other details not appropriate for a public tracker.

All accepted sponsorship relationships are documented in this file and reviewed
for governance independence before being announced.

---

_Last reviewed: 2026-05-20_
