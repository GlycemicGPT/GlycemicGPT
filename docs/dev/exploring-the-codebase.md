---
title: Exploring the Codebase
description: Get oriented fast — an AI-generated codebase wiki, plus the authoritative architecture docs.
---

GlycemicGPT is a multi-component monorepo (backend API, web app, AI sidecar, Android phone + Wear OS apps, device-data plugins). This page is a starting point for finding your way around.

## Ask DeepWiki (AI-generated overview)

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/GlycemicGPT/GlycemicGPT)

DeepWiki is an auto-generated, AI-powered wiki of this repository. It maps the architecture, summarizes components, and lets you ask questions about the code in natural language — a fast way to build a mental model before reading source.

It refreshes automatically (the DeepWiki badge in the project README keeps it on a weekly re-index), so it tracks the default branch without manual upkeep.

> **It is AI-generated, and can be incomplete or wrong.** Treat it as an orientation aid, never an authority — especially for anything safety-related. The source code, this `docs/` site, and the safety rules in [CONTRIBUTING](https://github.com/GlycemicGPT/GlycemicGPT/blob/develop/CONTRIBUTING.md) are the source of truth. When DeepWiki and the code disagree, the code is right.

## The authoritative references

When you need the real picture, start here:

- [Plugin Architecture](plugin-architecture.md) — how device-data drivers (pumps, CGMs) plug in, and the safety-limit contract every plugin must honor.
- [Wear OS Architecture](wear-os-architecture.md) — the phone ↔ watch data layer.
- [Branching Strategy](branching-strategy.md) — the develop → main flow and how releases are cut.
- [Local Dev Testing Checklist](testing-checklist.md) and [Security Testing](security-testing.md) — what to run before opening a PR.

## Repository layout (top level)

- `apps/api` — FastAPI backend (Python).
- `apps/web` — Next.js web app.
- `sidecar/` — the AI sidecar (provider abstraction for BYOAI).
- `apps/` Android modules + `plugins/` — the mobile app, Wear OS, and device-data drivers.
- `docs/` — this documentation site.
