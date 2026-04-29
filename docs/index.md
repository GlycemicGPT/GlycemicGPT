---
title: GlycemicGPT
description: Open-source AI-powered diabetes management you self-host.
---

GlycemicGPT is an open-source platform that brings together your diabetes data and gives you AI-powered insight into your patterns. You run it on your own infrastructure -- your data stays with you. The platform shows you what's happening in plain language and helps you have better conversations with your endocrinologist.

> **GlycemicGPT does not deliver insulin and is not a substitute for medical advice.** It's a monitoring and analysis tool that complements professional healthcare, not a replacement for it. Always consult your healthcare provider for medical decisions.

## How it works (and what you'll need)

GlycemicGPT has three things that work together:

1. **The platform** -- runs on a computer or server you control. It stores your data, runs the AI, and serves the dashboard you view in a browser.
2. **The Android companion app** -- runs on your phone. It connects to your insulin pump over Bluetooth and forwards data to the platform.
3. **An AI provider** -- GlycemicGPT does not host AI itself. You bring your own. Options include using an existing Claude or ChatGPT subscription you already pay for, providing a Claude or OpenAI API key, or running a local model like Ollama. See [BYOAI](./concepts/byoai.md) for the full picture and how to choose.

**All three are required today.** The platform alone cannot read pump data over Bluetooth -- that's the phone app's job. The platform also doesn't generate AI insights without an AI provider configured -- it's a relay between you and whichever provider you bring. (This may change as the project evolves and other data paths are added -- see [ROADMAP.md](../ROADMAP.md).)

A Wear OS watch face is also available but **optional**.

If a family member, friend, or other trusted person needs visibility into the platform too -- to receive escalated alerts, view your dashboard, or otherwise help support your care -- GlycemicGPT supports a [caregiver model](./caregivers/overview.md). Caregivers get their own opt-in, read-only access to your data on your platform.

## Where to start

### If you're new

**[Get started](./get-started.md)** -- the full walkthrough from zero to a working setup, including the mobile app.

**[Mobile app install](./mobile/install.md)** -- step-by-step Android install (the companion app is required to connect your pump).

### Installing the platform

**[Install with Docker](./install/docker.md)** -- the full Docker reference, including how to install Docker if you don't have it yet, plus walkthroughs for laptop, home server, and VPS deployments.

**[Install with Kubernetes](./install/kubernetes.md)** -- for users running their own cluster.

### Once you're up and running

**[Daily use](./daily-use/dashboard.md)** -- reading your dashboard, connecting your CGM and pump, using AI chat, daily briefs, and configuring alerts.

**[Caregivers](./caregivers/overview.md)** -- inviting a family member or other trusted person to help support your care.

**[Concepts](./concepts/what-this-software-is-and-isnt.md)** -- the honest scope of what GlycemicGPT does and doesn't do, the privacy story, BYOAI, and a glossary of diabetes and platform terms.

### When things go wrong

**[Troubleshooting](./troubleshooting/index.md)** -- find the symptom you're seeing and follow the path to fix it.

## Where you can run it

GlycemicGPT runs anywhere Docker runs. The Get Started guide covers all three of these end-to-end:

- **On your laptop or desktop** -- the simplest path for trying it out, with no public access
- **On a computer at home running all the time** (a desktop, mini-PC, NAS, or Raspberry Pi) -- with public access via [Cloudflare Tunnel](./install/docker.md#deploying-with-cloudflare-tunnel-home-server-or-vps), so you don't have to open any ports on your home network
- **On a cloud server you rent** (sometimes called a VPS -- think small monthly-fee cloud computer from Hetzner, DigitalOcean, etc.) -- with automatic HTTPS via [Caddy and Let's Encrypt](./install/docker.md#deploying-to-a-vps-with-https)

You can also bring your own reverse proxy or run it behind any existing infrastructure -- see [Install with Docker](./install/docker.md) for the full menu of options.

## Currently supported devices

| Device | Status |
|---|---|
| Dexcom G7 | Supported via cloud API |
| Tandem t:slim X2 | Supported via Bluetooth (through the mobile app) and cloud (t:connect) |

Support for additional pumps and CGMs is on the roadmap, along with integrations with other open-source diabetes platforms many people already use -- Nightscout, Loop, AAPS, xDrip. See [ROADMAP.md](../ROADMAP.md) for what's planned.

## What it does

- Real-time glucose monitoring with trend charts
- Time in Range tracking and pattern recognition
- AI chat that knows your data and answers questions in plain language
- Daily AI-generated briefs that summarize your day
- Configurable alerts that can reach you (and a caregiver) through multiple channels
- Printable reports for endocrinologist appointments
- Self-hosted -- all your data stays on infrastructure you control

## What it doesn't do

- It does not control your insulin pump or deliver insulin
- It does not replace your endocrinologist or healthcare team
- It does not phone home, collect telemetry, or share your data with anyone
- It does not use your data to train AI models

## Project status

GlycemicGPT is **alpha software** in active development. It's functional and in daily use by the project lead, but it has not been broadly tested. Use at your own risk.

## Get involved

- **Discord** -- [join the community](https://discord.gg/QbyhCQKDBs) for real-time chat, questions, and project discussion
- **GitHub** -- [GlycemicGPT/GlycemicGPT](https://github.com/GlycemicGPT/GlycemicGPT)
- **Roadmap** -- [where the project is going](../ROADMAP.md)
- **Contributing** -- [Contributing Guide](../CONTRIBUTING.md)
