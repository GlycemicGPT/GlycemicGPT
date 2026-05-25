# Privacy

GlycemicGPT is a privacy-first project. This is the short version. The canonical,
detailed privacy documentation lives in
[docs/concepts/privacy.md](docs/concepts/privacy.md) and is the single source of
truth; where this file and that one ever appear to differ, the canonical doc wins.

## In production: nothing is centralized

GlycemicGPT is self-hosted. Your data -- glucose readings, insulin and pump data,
AI chat, settings, credentials -- lives entirely in the database on infrastructure
you control. The platform does not phone home, collect telemetry, or transmit your
data to the project or any third party. The only outbound calls a running platform
makes are the ones you configure (your AI provider, your Dexcom/Tandem cloud, your
Telegram bot, your reverse proxy). See the
[canonical privacy doc](docs/concepts/privacy.md) for the complete data-flow map.

## Error monitoring: the project's own development only

The project uses [Sentry](https://sentry.io/), donated through
[Sentry for Good](https://sentry.io/for/good/), for error monitoring in **its own
development, CI, and staging environments** -- to catch crashes before they reach
a release.

No build the project distributes phones home. The Sentry DSN is supplied only via
an environment variable in maintainer-controlled environments; it is **never baked
into any published Docker image, web bundle, or Android APK -- production or
`develop`.** A build you pull and run reports nothing to the project's Sentry.

The project uses only the low-risk Sentry products that cannot carry your data --
error monitoring, cron and uptime checks, and performance profiling, all against
its own infrastructure. It **never enables Session Replay, log ingestion, or
event attachments** on any project-operated instance (including demos and
staging), because those would capture exactly the data listed below. Sentry's
on-demand paid budget is left disabled.

**What an error report contains** (from the project's own environments, or from a
self-hoster who opts in):

- Stack trace and exception type
- Operating system and runtime versions
- GlycemicGPT version and commit hash
- The line of code that triggered the error

**What an error report never contains:**

- Blood glucose readings or any health data
- User identifiers, names, or contact information
- API keys, tokens, or credentials
- Device serial numbers or pairing IDs
- Database contents or query parameters
- Local variables captured in error contexts
- HTTP request or response bodies
- Health data or identifiers interpolated into exception or log messages

> **Status:** The Sentry SDK integration is now shipped for the **API**
> (`apps/api`) and implements exactly the design above; it stays disabled unless
> `GLYCEMICGPT_SENTRY_DSN` is set in a maintainer-controlled environment. The
> ai-sidecar, web, and mobile components are not yet instrumented.

## Controlling error monitoring

- **Default -- nothing to opt out of.** Distributed builds carry no Sentry DSN,
  so a build you pull and run reports nothing to anyone; there is no project
  telemetry to disable. For general use, production Docker tags (built from
  `main` releases) are the supported path.
- **Belt and suspenders.** If a future `develop` build ever ships with Sentry
  wiring, the control is the `GLYCEMICGPT_SENTRY_DSN` environment variable --
  unset by default in every distributed build, which keeps error reporting off.
- **Opt in for your own deployment.** If you *want* error monitoring for your
  self-hosted deployment, set your own `GLYCEMICGPT_SENTRY_DSN`. Reports then go
  to *your* Sentry account, never the project's.

## Privacy questions

Report privacy concerns the same way as security disclosures: use
[GitHub Security Advisories](https://github.com/GlycemicGPT/GlycemicGPT/security/advisories/new)
for sensitive issues, or
[GitHub Issues](https://github.com/GlycemicGPT/GlycemicGPT/issues/new/choose) for
general privacy questions. Privacy is load-bearing for the project; reports here
are taken seriously.

---

_Canonical version: [docs/concepts/privacy.md](docs/concepts/privacy.md). Last reviewed: 2026-05-20._
