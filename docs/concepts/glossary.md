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

The backend services (web, API, AI bridge, database, cache). What you run with `docker compose up -d`.

### AI bridge

A small service that lives between the main GlycemicGPT API and whichever AI provider you've chosen. When you chat with the AI, your message goes through the AI bridge, which forwards it to your configured provider (Claude, OpenAI, Ollama, etc.) and streams the response back. Keeping the AI bridge separate means the rest of the platform doesn't need to know which AI provider you're using -- you can switch providers without re-deploying anything.

In Docker `docker compose ps` output the AI bridge appears as `sidecar` (or `ai-sidecar`) -- that's the literal service name. You'll occasionally see it called "sidecar" or "the relay" in older docs or technical contexts; it's the same thing.

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

## Tools mentioned during setup

These show up in the install steps but aren't really "diabetes" or "GlycemicGPT" terms -- they're general computing tools.

### Terminal

A text-based way to control your computer. You type a command, the computer runs it. Already installed on every Mac (search "Terminal"), every Linux machine, and every Windows machine (Windows users open PowerShell or, after WSL2 setup, a Linux terminal). See [the terminal note in Get Started](../get-started.md#a-note-on-the-terminal).

### Docker

A way to package software so it runs the same way on every computer. GlycemicGPT ships as a set of Docker components; you install Docker once and the platform runs on top of it. The thing called "Docker Compose" runs a group of related Docker services together with one command. See [Install with Docker](../install/docker.md).

### Git

A version-control tool. Most developers use it daily. As a GlycemicGPT user, you only need it once -- to download the platform's source files in step 2 of [Get Started](../get-started.md). The fallback (download a ZIP from GitHub) avoids needing git at all.

### Node.js

A way to run JavaScript programs outside a web browser. You only need this if you're using Option 1 or 2 of the AI provider setup (Claude / ChatGPT subscription) -- those require running a small Anthropic or OpenAI command-line tool, and that tool is built on Node.js. Download from [nodejs.org](https://nodejs.org).

### npx

A command that comes with Node.js. It runs a tool from the internet without installing it permanently. The Claude and ChatGPT subscription token-setup commands use npx so you don't have to install anything you'll never use again.

### openssl

A tool for generating random secrets. Comes pre-installed on macOS and Linux. On Windows it's installed automatically as part of WSL2. The `openssl rand -hex 32` command in step 3 of [Get Started](../get-started.md) just generates a random string used as a secret key.

### sudo

The command on Linux (and macOS) for running something with administrator privileges. When you see `sudo apt install ...` or similar, that's installing software with admin rights. Mac users may be prompted for their password the first time; Linux users will be too.

### OAuth / Token

OAuth is the authentication system most modern services use to let one app act on your behalf. A "token" is the long string of letters and numbers a service hands you after you sign in -- it's what GlycemicGPT stores instead of your password. The Claude / ChatGPT subscription setup is an OAuth flow: you sign in to Anthropic or OpenAI in your browser, they hand back a token, you paste it into GlycemicGPT.

### API key

A long string of letters and numbers that identifies you to a service for billing and access purposes. Anthropic and OpenAI each give you API keys from their console. Think of it as a password for programs (rather than for humans).

### Endpoint

A URL that a program talks to. When the BYOAI setup says "OpenAI-compatible endpoint," it means a URL that speaks the same language as OpenAI's API -- like a local Ollama server, or LM Studio, or a third-party hosting service. You'll only encounter this if you choose Option 5.

### Redis

A small database for short-lived data (sessions, cached values). The platform runs Redis as one of its services. You don't interact with it directly; it just runs alongside the rest of the platform.

### IP address

A number like `192.168.1.42` that identifies a computer on a network. When the docs say "your computer's IP," they mean the local-network address of the machine running the platform (not your home's public address). See [the mobile install page](../mobile/install.md#step-1-download-the-apk) for how to find yours on each operating system.
