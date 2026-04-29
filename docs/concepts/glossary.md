---
title: Glossary
description: Plain-language definitions of terms you'll see across the platform.
---

A reference for terms that appear in the dashboard, AI chat, briefs, and these docs. Defined for someone who doesn't have a diabetes-tech vocabulary.

## Diabetes terms

### BG -- Blood Glucose

The amount of sugar in your blood, measured in mg/dL (US) or mmol/L (most other countries). Your CGM reports BG continuously.

### CGM -- Continuous Glucose Monitor

A small sensor worn on your body that measures BG every few minutes and transmits it to your phone (or pump). Examples: Dexcom G7, Freestyle Libre, Medtronic Guardian. GlycemicGPT supports Dexcom G7 today; others are on the roadmap.

### Time in Range (TIR)

The percentage of time your BG was in your target zone over a given window (24 hours, a week, a month). A clinically common metric for how well-controlled your diabetes is. Targets vary -- ask your endocrinologist what's right for you.

### Insulin on Board (IoB)

The amount of bolus insulin still active in your system, calculated from your recent boluses and your insulin's "duration of action" (typically 3-5 hours, depending on the insulin type and your physiology). IoB matters because if you have a lot of active insulin, additional dosing risks going low.

### Carbs on Board (COB)

The amount of carbohydrate from your recent meal that hasn't been processed yet. Used in calculations for how IoB and incoming carbs will balance out. Less directly visible in GlycemicGPT today than IoB, but relevant for predictive analytics in the roadmap.

### Bolus

A discrete dose of insulin you give yourself (or your pump delivers) for a meal or to correct a high reading.

### Basal

A continuous trickle of insulin your pump delivers throughout the day to maintain background insulin levels (in the absence of meals). Configured as a "basal rate" in units per hour, can vary by time of day.

### Carb ratio (I:C)

How much insulin to dose per gram of carbohydrate. e.g., 1:10 means 1 unit of insulin per 10 grams of carbs. Set in your pump or calculated manually.

### Correction factor / ISF (Insulin Sensitivity Factor)

How much one unit of insulin lowers your BG. e.g., ISF of 50 means 1 unit of insulin lowers BG by 50 mg/dL. Used to dose corrections for high readings.

### Trend arrow

The direction your BG is moving on the dashboard chart. CGM systems typically report something like:

- ↑ rising fast (~3+ mg/dL/min)
- ↗ rising
- → steady
- ↘ falling
- ↓ falling fast

The exact thresholds depend on the CGM device.

### Hypo / hyper

- **Hypoglycemia (hypo):** BG too low. Symptoms range from mild (shaky, hungry) to severe (loss of consciousness). Below 70 mg/dL is typically considered hypo; below 55 is urgent.
- **Hyperglycemia (hyper):** BG too high. Long-term high BG causes complications; short-term very high BG (300+ mg/dL with ketones) can lead to DKA.

### DKA -- Diabetic Ketoacidosis

A serious complication of high BG with insulin deficiency. Requires emergency medical attention. GlycemicGPT does not detect DKA; if you suspect it, contact your healthcare provider or emergency services immediately.

### Pump

An insulin pump -- a small device worn on your body that delivers insulin continuously (basal) and on-demand (bolus) through a cannula. Examples: Tandem t:slim X2, Tandem Mobi, Omnipod, Medtronic 780G. GlycemicGPT supports Tandem t:slim X2 today.

### t:connect

Tandem's official mobile app and cloud service for syncing pump data. GlycemicGPT can read from t:connect's cloud (see [Connecting Your Tandem Pump](../daily-use/connecting-tandem-cloud.md)).

### Closed-loop / artificial pancreas

A system where software algorithms automatically adjust insulin delivery based on CGM data. Examples: Tandem Control-IQ, Medtronic 780G's SmartGuard, Loop, AndroidAPS. **GlycemicGPT is not a closed-loop system** -- see [What This Software Is and Isn't](./what-this-software-is-and-isnt.md).

## GlycemicGPT-specific terms

### Platform

The backend services (web, API, sidecar, database, cache). What you run with `docker compose up -d`.

### Sidecar

The AI relay service. When you chat with the AI, your message goes through the sidecar, which forwards it to your configured AI provider and streams the response back. The sidecar isolates the AI provider integration from the main API.

### BYOAI -- Bring Your Own AI

The platform's AI model: you provide your own AI credential (existing subscription token or API key) instead of paying the project for AI access. See [BYOAI](./byoai.md).

### RAG -- Retrieval Augmented Generation

A technique for giving an AI access to information it wasn't trained on by retrieving relevant documents at query time and including them in the prompt. GlycemicGPT uses RAG to give the AI access to a curated diabetes knowledge base (peer-reviewed research, NIH guidelines, etc.).

### Companion app / mobile app

The Android app that connects to your insulin pump over Bluetooth and forwards data to the platform. Required for live pump data; optional for users only using a Dexcom CGM via cloud. See [Install the Android App](../mobile/install.md).

### Watch face

The optional Wear OS watch face that shows glucose / IoB / trend at a glance. See [Install the Wear OS Watch Face](../mobile/wear-os.md).

### Caregiver

A trusted person who has read-only access to your data, with optional alert escalation. See [Caregivers Overview](../caregivers/overview.md).

### Brief / Daily brief

An AI-generated summary of your data over a window (typically a day). See [Daily Briefs](../daily-use/briefs.md).

### Plugin SDK

The library that lets developers add support for new diabetes devices (other CGMs, other pumps, etc.). Read-only by design -- no plugin can deliver insulin or modify pump settings, by architectural constraint, not just by convention. See [Plugin Architecture](../dev/plugin-architecture.md).

## Deployment terms

### Self-hosted

Running the platform on infrastructure you control (your laptop, your home server, your VPS). The default deployment model for GlycemicGPT.

### Always-on deployment

A deployment that runs 24/7 and is publicly reachable -- a cloud VPS or a home server with a Cloudflare Tunnel. Required if your mobile app needs to reach the platform from anywhere.

### Cloudflare Tunnel

A service from Cloudflare that exposes your server (home or VPS) publicly without port forwarding or any inbound ports open. See [Install with Docker -- Deploying with Cloudflare Tunnel](../install/docker.md#deploying-with-cloudflare-tunnel-home-server-or-vps).

### VPS

Virtual Private Server. A small cloud computer you rent (Hetzner, DigitalOcean, Linode, AWS Lightsail, etc.) that you can SSH into and run software on.

### Reverse proxy

Software (Caddy, nginx, Cloudflare's edge) that sits in front of your platform and handles HTTPS, routing, and access control. The deploy examples include Caddy or Cloudflare Tunnel as the reverse proxy.

### Kustomize / Helm

Kubernetes deployment tooling. Kustomize is the simpler one -- it composes plain YAML manifests with overlays. Helm uses templated charts. The platform ships Kustomize manifests today; a Helm chart is on the roadmap. See [Install with Kubernetes](../install/kubernetes.md).

### Sideload

Installing an app on a device without going through an official app store. The Android phone app and Wear OS watch face are both sideloaded today. See [Install the Android App](../mobile/install.md) and [Install the Wear OS Watch Face](../mobile/wear-os.md).

### ADB -- Android Debug Bridge

The command-line tool for talking to an Android device or Wear OS watch from a computer. Required for sideloading the watch face today. See [Install the Wear OS Watch Face](../mobile/wear-os.md).
