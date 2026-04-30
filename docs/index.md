---
title: GlycemicGPT
description: Self-hosted diabetes monitoring with an AI chat layer over your own CGM and pump data.
---

GlycemicGPT reads your CGM and your insulin pump, stores the data on a server you control, and lets you ask plain-English questions about it. "What happened overnight?", "is there a pattern in my dawn-phenomenon highs?", "did the post-meal correction land?" -- the AI chat answers from your own history, grounded in clinical references. Daily AI-written briefs and configurable alerts run on the same data.

If you're already running [Nightscout](https://nightscout.github.io/), [Loop](https://loopkit.github.io/loopdocs/), [AAPS](https://androidaps.readthedocs.io/), [xDrip+](https://github.com/NightscoutFoundation/xDrip), or [Tidepool](https://www.tidepool.org/) -- GlycemicGPT is designed to coexist with those, not replace them. See [Relationship to other tools](./concepts/relationship-to-other-tools.md) for the honest comparison.

> **GlycemicGPT does not deliver insulin and is not a substitute for medical advice.** It's a monitoring and analysis tool that complements professional healthcare, not a replacement for it. Always consult your healthcare provider for medical decisions.

## How it works (and what you'll need)

GlycemicGPT has three pieces that work together:

1. **The platform** -- runs on a computer or server you control. It stores your data, runs the AI features, and serves the dashboard you view in a browser.
2. **The Android companion app** -- runs on your phone. It connects to your insulin pump over Bluetooth and forwards data to the platform.
3. **An AI provider** -- GlycemicGPT does not host AI itself. You bring your own. The simplest option is using a Claude or ChatGPT subscription you already pay for; other options exist too. See [BYOAI](./concepts/byoai.md) for the full picture and how to choose.

Setup wires these together so they talk to each other. Each piece has a specific job: the phone app gets pump data into the platform; the AI provider answers your chat questions; the platform pulls everything together and shows it to you. (As the project evolves, other ways of connecting these may become available -- see [ROADMAP.md](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/ROADMAP.md).)

A Wear OS watch face is also available but **optional**.

> **iPhone users:** the web dashboard, AI chat, daily briefs, alerts, and Dexcom integration all work fine in iPhone Safari -- no Android phone needed for any of that. The Android companion app is only required for **live Bluetooth pump data**. If you don't have a pump (or you're fine with cloud-only pump data via t:connect), an iPhone alone covers most of what GlycemicGPT does. iOS companion app support is on the [roadmap](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/ROADMAP.md).

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

The honest matrix. "Verified" means daily-tested on real hardware; "expected to work" means the protocol path is implemented but the project lead doesn't have the hardware to verify continuously; "planned" means on the roadmap; "not supported" means not today and not actively planned (file an issue if it should be).

### CGMs

| CGM | Status | Notes |
|---|---|---|
| Dexcom G7 | **Verified** | Cloud-API path, polled from Dexcom every 5-10 min. Project lead's daily-driver CGM. |
| Dexcom G6 | **Expected to work** | Same cloud-API path as G7 (pydexcom supports both); not continuously tested by the project. |
| Dexcom Stelo | **Not yet** | Planned once the underlying library adds Stelo support. |
| Freestyle Libre 2 / 3 / 3+ | **Not supported today** | Roadmap. Recommended path until then: xDrip+ → Nightscout, then Phase 2 Nightscout integration. |
| Eversense | **Not supported today** | Roadmap. |
| Medtronic Guardian | **Not supported today** | Tied to Medtronic pump support; see roadmap. |

### Insulin pumps

| Pump | Status | Notes |
|---|---|---|
| Tandem t:slim X2 | **Verified** (BLE + cloud) | Project lead's daily-driver pump. Bluetooth path via the mobile app gives live data; t:connect cloud path gives history. |
| Tandem Mobi | **Driver implemented, hardware-unverified** | The Mobi shares most of the t:slim X2 protocol; the driver compiles and treats Mobi as supported, but the project lead does not own a Mobi for continuous verification. Field reports welcome via [Discord](https://discord.gg/QbyhCQKDBs). |
| Omnipod (DASH / Eros) | **Not supported today** | Roadmap. |
| Medtronic 5xx / 7xx series | **Not supported today** | Roadmap. |
| Dana RS / Dana-i | **Not supported today** | Roadmap. |
| Accu-Chek Combo | **Not supported today** | Roadmap. |

For Tandem users: the Bluetooth and cloud paths complement each other -- Bluetooth gives live data, cloud fills in history. Most people end up using both. See [Connecting Your Tandem Pump](./daily-use/connecting-tandem-cloud.md).

If your device isn't here today, the path forward is usually [Nightscout integration (Phase 2)](./concepts/relationship-to-other-tools.md#nightscout) -- once that lands, anything that flows into Nightscout flows into GlycemicGPT. See [ROADMAP.md](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/ROADMAP.md) for the full picture.

## What's distinctive

What GlycemicGPT does that the existing OSS tools don't:

- **AI chat over your own data**, grounded in clinical references via retrieval-augmented generation. Ask questions in plain English and get answers that reason over *your* glucose history, *your* boluses, *your* basal patterns -- not generic diabetes information. ([How AI chat works](./daily-use/ai-chat.md))
- **Daily / weekly AI-written briefs** that summarize what happened in prose, not just statistics, and surface novel patterns worth following up on with the AI chat. ([Daily briefs](./daily-use/briefs.md))

What it shares with the existing OSS tools (table stakes; not novel):

- Real-time glucose monitoring with trend charts
- Time in Range tracking
- Configurable alerts with caregiver escalation
- Printable reports for endocrinologist appointments (note: AGP-style reports are roadmap; today's reports are summary-style)
- Self-hosted -- all your data stays on infrastructure you control

## What it doesn't do

- It does not control your insulin pump or deliver insulin
- It does not replace your endocrinologist or healthcare team
- It does not phone home, collect telemetry, or share your data with anyone
- It does not use your data to train AI models

## What it costs

GlycemicGPT itself is free and open source. The platform, the Android app, and the watch face all cost nothing. You will, though, end up paying for some pieces of what makes it work:

- **An AI provider.** This is the only meaningful recurring cost, and it can vary widely. If you already pay for [Claude](https://claude.ai) (Pro / Max) or [ChatGPT](https://chat.openai.com) (Plus / Team), you can plug that in and pay nothing extra -- subscription tiers cap your cost at the monthly subscription price. If you use Anthropic or OpenAI **API keys** directly, you pay per token used; daily AI briefs and active AI chat sessions can add up. The project has not yet measured typical costs in a publishable way; we recommend setting a billing limit on your provider account and watching the first month. See [BYOAI -- realistic cost ranges](./concepts/byoai.md#realistic-cost-ranges) for an honest discussion. Running a local model is free but requires a beefier computer.
- **A computer to run the platform on.** A laptop or desktop you already own is fine. If you'd rather not leave your laptop on all the time, a small always-on machine (mini-PC, Raspberry Pi, NAS, or a $5-10/month cloud server) covers it.
- **(Optional) A domain name** if you want a friendly URL like `glucose.yourname.com` for accessing the platform from anywhere. Around $10-15/year. Not required if you only use it on your home network.

There are no per-user fees, no premium tier, no subscription to GlycemicGPT itself. See [BYOAI](./concepts/byoai.md) for the full breakdown of AI provider options and cost.

## Project status

GlycemicGPT is **alpha software** in active development. It's functional and in daily use by the project lead, but it has not been broadly tested. Use at your own risk.

## Get involved

- **Discord** -- [join the community](https://discord.gg/QbyhCQKDBs) for real-time chat, questions, and project discussion
- **GitHub** -- [GlycemicGPT/GlycemicGPT](https://github.com/GlycemicGPT/GlycemicGPT)
- **Roadmap** -- [where the project is going](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/ROADMAP.md)
- **Contributing** -- [Contributing Guide](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/CONTRIBUTING.md)
- **Governance** -- [how the project is run](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/GOVERNANCE.md)
- **Acknowledgments** -- [the projects this one stands on](./concepts/acknowledgments.md)
