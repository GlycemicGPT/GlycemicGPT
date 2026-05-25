---
title: Privacy and Your Data
description: Where your data lives, where it flows, and what the project commits to.
---

GlycemicGPT is a privacy-first project. This page is the honest version: where your data actually goes, what the project commits to, and where the edges are.

## What "privacy-first" means in practice

The project's [Privacy-First guiding principle](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/ROADMAP.md) states:

> User health data stays on user-controlled infrastructure. The platform does not phone home, collect telemetry, transmit data to GlycemicGPT or any third party, or use user data to train AI models.

This is a load-bearing commitment, not marketing language. Concretely:

- **No telemetry.** The platform makes zero outbound calls to GlycemicGPT-controlled servers. There is no analytics endpoint, no usage tracking, no "phone home" of any kind.
- **No data exfiltration.** The platform does not transmit your data anywhere except where you've explicitly configured it (your AI provider, your Cloudflare/VPS, your Telegram bot if you've set one up).
- **No training.** The project does not use user data to train AI models. Period. This is documented in `ROADMAP.md` Privacy-First principle as a commitment, not just a current behavior.

## Where your data actually lives

### On your platform's database

The platform stores all your data in PostgreSQL on the infrastructure you've deployed:

- Glucose readings
- Insulin / pump data
- AI chat conversations
- Daily briefs
- Alert history
- Settings and preferences
- Account credentials (passwords are hashed, integration credentials like Dexcom Share are encrypted with your `SECRET_KEY`)

That database lives on:

- Your laptop's disk (if you're trying it locally)
- Your home server's disk (always-on Cloudflare Tunnel deployment)
- Your VPS provider's disk (cloud VPS deployment)

You control the disk. You control the backups. The project doesn't.

### Where data flows out

The platform makes outbound network calls in only these cases:

1. **To your AI provider** -- when you use AI chat or briefs are generated, the relevant data goes to whichever AI provider you've configured (Claude, OpenAI, your local Ollama, etc.). The provider has their own data policies; the project does not control those.

2. **To your Dexcom / Tandem cloud** -- if you've configured those integrations, the platform polls them for data. This is the same data flow that happens when you use the official Dexcom or Tandem apps; GlycemicGPT just routes it through your platform.

3. **To Telegram** (if you've configured the Telegram bot) -- alert deliveries and AI chat messages go through Telegram's servers.

4. **To your Cloudflare / Caddy / cloudflared connector** (depending on deployment) -- inbound traffic to your platform is decrypted at your reverse proxy. For VPS deployments using Caddy, the proxy runs on your server. For Cloudflare Tunnel, the proxy is at Cloudflare's edge -- they can technically see encrypted HTTPS traffic but, by their stated terms, do not inspect Tunnel traffic for normal use.

5. **To container registries during build / update** -- when you run `docker compose pull`, you fetch the GlycemicGPT images from `ghcr.io/glycemicgpt/...`. This is a one-way pull; no user data goes back.

There are no other outbound calls.

## Error monitoring in the project's own development

The project uses [Sentry](https://sentry.io/) -- donated through the [Sentry for Good](https://sentry.io/for/good/) open-source program -- for error monitoring in **its own development, CI, and staging environments**. The purpose is narrow: catch and triage crashes during development, before they reach a release.

This does not change anything above. To be explicit:

- **No build the project distributes phones home.** The Sentry DSN (the credential that directs error reports to an account) is supplied only through an environment variable in maintainer-controlled environments. It is **never baked into any published Docker image, web bundle, or Android APK** -- production *or* `develop`. A build you pull and run sends nothing to the project's Sentry, because it has no DSN to send to.
- **Production releases are telemetry-free, and so are distributed `develop` builds.** The `develop` tag exists for testing pre-release features; it is not a channel for collecting your error data.
- **You can opt your own deployment in.** If you *want* error monitoring for your self-hosted deployment, you can set your own Sentry DSN. Error reports then go to **your** Sentry account, never the project's. This is a feature for operators who want it, off by default.

> **Status:** The Sentry SDK integration is shipped for the **API** (`apps/api`), **ai-sidecar** (`sidecar/`), and **web** (`apps/web`, server-side only) components -- each implements exactly the design described here and stays disabled unless its own `*_SENTRY_DSN` environment variable is set in a maintainer-controlled environment. The mobile app is not yet instrumented.

### Which Sentry features the project uses -- and which it never enables

Sentry for Good grants a broad set of products. The project deliberately uses only the low-risk subset that cannot carry your data, and **declines the ones that could**.

**Used** -- against the project's own development, CI, staging, and public infrastructure:

- **Error monitoring** -- crashes and exceptions, scrubbed of the data listed below
- **Cron monitoring** -- whether the project's own scheduled jobs ran (run/miss/duration only)
- **Uptime monitoring** -- availability pings against the project's own public endpoints
- **Performance profiling and tracing** -- CPU/UI profiles and request traces in development and staging, with sensitive parameters scrubbed

**Never enabled** -- on any project-operated instance, including demos and staging:

- **Session Replay** -- it records what's on screen, and on a glucose dashboard that is exactly the data we refuse to collect
- **Log ingestion** -- application logs routinely contain health data and identifiers
- **Event attachments** -- screenshots or files attached to errors can carry the same

These three are declined precisely because they would carry the data the next section says we never send. Sentry's on-demand (paid overage) budget is also left disabled, so usage stays within the donated quota.

### What error reports contain (and what they never contain)

When the project's own development environment reports an error to Sentry -- or when a self-hoster opts their own deployment in -- the integration is designed so reports carry only diagnostic context, never your data. Reports include:

- The stack trace and exception type
- Operating system and runtime versions
- The GlycemicGPT version and commit hash
- The line of code that triggered the error

Reports will be configured to **never** include:

- Blood glucose readings or any health data
- User identifiers, names, or contact information
- API keys, tokens, or credentials
- Device serial numbers or pairing IDs
- Database contents or query parameters
- Local variables captured in error contexts
- HTTP request or response bodies
- Health data or identifiers interpolated into exception or log messages

These exclusions will be enforced in the SDK configuration (no default PII collection, local-variable capture disabled, request/response bodies dropped, and an event scrubber that redacts the categories above -- including values interpolated into exception or log messages) -- not left to chance. The project's contribution guidelines will likewise prohibit embedding health data or identifiers in exception messages.

## What about the project's hosted service?

The roadmap (Phase 4) includes a "hosted service for non-technical users" -- a managed deployment for users who don't want to run their own infrastructure. **The hosted service is not yet available**; this section is forward-looking.

When it launches:

- It will be a managed deployment of the same open-source software you can self-host today
- The project will host the platform; the user's data will live on the project's infrastructure
- The same Privacy-First principle applies -- no telemetry, no data sharing, no training on user data
- AI provider configuration follows the same BYOAI model -- users plug in their own credential (subscription token or API key); the hosted service does not act as an AI provider itself

If your threat model excludes "the project's infrastructure," self-hosting remains the primary supported path. The hosted service is for users who don't want to run their own servers; it isn't replacing self-hosting.

## What can your AI provider see?

When you chat with the AI, your message and the relevant context (recent glucose, IoB, etc.) are sent to your configured AI provider. They see:

- The text of your message
- The data context the platform attached (glucose history, recent boluses, etc.)
- The AI's response

What each provider does with that data depends on their terms:

- **Claude (Anthropic)** -- per Anthropic's policies, API traffic and Pro/Max subscription traffic is not used for training by default
- **OpenAI** -- per OpenAI's policies, API traffic is not used for training by default; ChatGPT subscription traffic policy varies by plan
- **Ollama / local models** -- the data does not leave your network at all; you control 100% of the path

If your privacy threshold is "data must not leave my network," use a local model via Ollama. If you're comfortable with cloud AI providers' standard terms, use whichever fits your budget / model preferences.

## What about the third parties involved?

Depending on your deployment, third parties touch your traffic in transit:

- **Cloudflare** (if you're using the Cloudflare Tunnel deployment) -- Cloudflare's edge sees encrypted HTTPS traffic. Per their terms, they do not inspect Tunnel traffic for normal use. If Cloudflare is in your threat model, use Caddy + Let's Encrypt on a VPS instead.
- **Your VPS provider** (if you're using a cloud VPS) -- they have access to the disk and memory of the VM. If your VPS provider is in your threat model, run on a home server.
- **Your ISP** -- sees encrypted HTTPS traffic to/from your platform. They cannot read what's inside.

For the highest privacy threshold (no third-party providers in any path), self-host on a home server with no public exposure (only accessible on your home network) and use a local Ollama model. The platform supports this configuration.

## Backups and data deletion

### Backups

The K8s deployment includes an automated PostgreSQL backup CronJob (daily, configurable retention). The Docker deployment doesn't have automated backups built in; for production-grade deployments you'd add `pg_dump` to a host cron job pointing at the database container.

Backups live wherever you put them -- the platform doesn't manage off-machine backup destinations.

### Deletion

You can delete your account and associated data through **Settings → Account → Delete account**. This removes all your data from the platform's database.

If you want to delete the entire platform, `docker compose down -v` deletes all volumes including the database. The disk and underlying VM/server retain whatever was there before, but the platform's data is gone.

## Reporting privacy issues

If you discover a privacy bug -- the platform leaking data, calling somewhere it shouldn't, or behaving inconsistently with this page -- report it through [GitHub Issues](https://github.com/GlycemicGPT/GlycemicGPT/issues/new/choose) (or Security Advisories for sensitive issues). Privacy is load-bearing for the project; bugs here are taken seriously.
