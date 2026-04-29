---
title: What This Software Is and Isn't
description: The honest scope of GlycemicGPT.
---

GlycemicGPT is a **monitoring and analysis platform** for people with diabetes and the people who care for them. This page describes -- in plain language, with no marketing -- what the platform does, what it doesn't do, and where the edges are.

## What it is

GlycemicGPT is software you run on your own infrastructure that:

- **Reads data from your diabetes devices** (CGMs, insulin pumps) so you have it all in one place
- **Shows that data on a dashboard** that's easier to read than scrolling through individual device apps
- **Surfaces patterns** that are hard to spot manually -- recurring highs at certain times of day, missed boluses, unusual trends
- **Has an AI you can ask questions** about your data in plain language
- **Generates daily summaries** of what's been happening
- **Sends alerts** when your glucose crosses thresholds you set, with optional escalation to a caregiver

It's open source. You self-host it. You bring your own AI provider (your existing Claude or ChatGPT subscription, your own API key, or a local model). Your data stays on infrastructure you control.

## What it isn't

This is not a complete list, but it covers the things people most often expect or hope it does:

### It is not an artificial pancreas / closed-loop system

GlycemicGPT does not control your insulin pump. It does not deliver bolus, modify basal rates, or change any pump setting. It reads data; it does not write commands.

If you want a closed-loop system (where software algorithms automatically adjust insulin delivery), look at [Loop](https://loopkit.github.io/loopdocs/) or [AndroidAPS](https://androidaps.readthedocs.io/) -- those projects are designed for that and have been operating in production for years. GlycemicGPT is a different kind of tool: monitoring and analysis, not closed-loop.

### It is not a medical device

The platform does not have FDA clearance, CE marking, or any regulatory approval as a medical device. It's research / personal-use software shared under GPL-3.0.

This means:

- You use it at your own risk
- It cannot legally make medical claims
- It does not give medical advice (and is configured to refuse / deflect when asked to)
- Any AI-generated insights are informational starting points, not clinical assessments

### It does not replace your endocrinologist

Your healthcare team has training, clinical judgment, and a complete view of your medical history that no software can replicate. GlycemicGPT can help you have better conversations with your endo (e.g., showing patterns you might otherwise miss, generating printable reports for appointments). It does not substitute for those conversations.

### It does not phone home, and it does not use your data to train AI models

The platform does not transmit telemetry, analytics, or any data to GlycemicGPT's developers, the project, or any third party. The only places your data flows:

- Stays on your platform's database (you control the infrastructure)
- Goes to your configured AI provider when you chat with the AI (Claude, OpenAI, your local Ollama -- whichever you set up). The provider sees your messages, like any other AI service. The provider has their own retention and training policies; the project does not control those.
- Goes to your Cloudflare or VPS provider if you've deployed it there (they see encrypted HTTPS traffic, same as any web service)

The platform is also explicit, as a load-bearing project commitment: **no user data is used to train AI models**. This is documented in [Privacy](./privacy.md) and in the project's [Privacy-First guiding principle](../../ROADMAP.md).

### The mobile app is not a closed-loop interface

The Android app reads data from your pump and forwards it to the platform. It cannot deliver insulin, change settings, or send any write command. This is a deliberate design choice -- the plugin SDK that the app uses has no write primitives at all.

### The plugin SDK does not enable insulin delivery

The plugin system the platform uses for adding device support is read-only by design. The capability set is enumerated and limited; there are no "insulin delivery" or "pump control" capabilities exposed. Forks of the project that modify the SDK to add such capabilities operate outside the project; their users become the manufacturer of their personal medical device, consistent with the legal posture of Loop and AndroidAPS.

## Edge cases worth being explicit about

### "Can the AI tell me how much insulin to take?"

No. The AI is configured to refuse / deflect on specific dosing recommendations. It can tell you what your insulin-on-board curve looks like, what it observes about your responses to past meals, what patterns it noticed -- but it will not say "take 4 units now." That's a clinical judgment that requires your healthcare team.

### "Can the AI predict my glucose?"

Predictive glucose modeling is on the roadmap (ROADMAP §Phase 4) but as **deterministic mathematical models, not LLM-based generation**. LLMs hallucinate; using one to forecast a number a person will dose against is a bad idea. The roadmap predictive models will use IoB / COB / trend math, with auditable confidence indicators -- explicitly NOT free-form AI text predictions.

### "Can I trust the dashboard's numbers?"

The dashboard reflects what your devices reported. Devices have their own error modes (sensor drift, transmitter issues, paired-device conflicts). Always cross-reference with the device's official app for any value that looks wrong, and never make medical decisions based on a dashboard value you haven't verified.

### "Is the project regulated?"

Not as a medical device, no -- and the project's positioning is explicitly to stay out of medical-device classification by being monitoring-only. The platform may be subject to general privacy / security regulations depending on where you deploy it (HIPAA in the US if a covered entity is involved, GDPR in Europe), but those are deployment concerns for the operator, not the software itself.

## Why monitoring-only?

Monitoring-only is a deliberate scope decision, not a limitation we wish were different. Reasons:

- It keeps the project clearly outside FDA medical-device classification, which is essential for an open-source project without the resources to pursue clearance
- It aligns with the project's [Privacy-First](./privacy.md) principle -- read paths have a much smaller blast radius than write paths
- It honors the precedent of how monitoring-and-analysis tools have historically been distributed: as patient-empowering software, not regulated devices
- It complements rather than competes with closed-loop projects like Loop and AAPS -- those projects are right for users who want closed-loop; GlycemicGPT is right for users who want comprehensive monitoring + AI insight

If you want closed-loop, use Loop or AAPS. If you want monitoring + AI analysis on data you control, GlycemicGPT is for you.

## What about the future?

The [project roadmap](../../ROADMAP.md) lays out where things are going. The monitoring-only stance is permanent for the project's first-party releases. Major near-term items: more device support, integrations with platforms like Nightscout, mobile app refinement, behavioral pattern detection (still in monitoring/analysis territory). Closed-loop is explicitly out of scope.
