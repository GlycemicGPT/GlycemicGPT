---
title: Get Started
description: From zero to a working GlycemicGPT setup -- platform, mobile app, and (optionally) the watch face.
---

This guide walks you through setting up GlycemicGPT end-to-end: the platform itself, the Android companion app you need to connect your pump, and the optional watch face.

## Pick your path

You can run GlycemicGPT in two ways:

| If you... | Choose this path |
|---|---|
| Want to try it out before committing to anything | **Try it locally** -- run on your own laptop or desktop |
| Plan to use it day-to-day with your phone reaching it from anywhere | **Always-on deployment** -- a home server, mini-PC, NAS, Raspberry Pi, or a small cloud server you rent (sometimes called a VPS) |

You can always start locally and migrate to an always-on setup later -- your settings and data live in the database, and the platform itself is the same.

> **Before you start, you need:**
>
> - **A computer to run the platform on** -- a laptop, desktop, home server, or rented cloud server. The platform is light:
>   - **RAM:** 2 GB minimum, 4 GB recommended. (One part of the platform uses about 1 GB on its own to do the AI knowledge-base lookup; the rest is light.)
>   - **Disk:** 5 GB minimum, 10 GB recommended. The platform's files take about 3 GB; the rest grows slowly with your data over time.
>   - **CPU:** any modern dual-core works. The platform sits mostly idle except when the AI is answering a question.
>   - **OS:** macOS, Linux, or Windows. **Windows users:** see the note below before you start -- you'll need to install one extra Microsoft component first.
> - **An Android phone** for the companion app (required to connect your pump over Bluetooth)

> **Windows users only:** GlycemicGPT runs on Linux software. Windows lets you run that software through a Microsoft feature called **WSL2** (Windows Subsystem for Linux 2). It's free and Microsoft-supported, but it does add some setup steps before this guide. Plan to spend roughly an extra half-hour up front following [Microsoft's WSL2 setup guide](https://learn.microsoft.com/en-us/windows/wsl/install). After that, the rest of this guide works the same as it does on macOS or Linux. macOS and Linux users can skip this note.

## A note on the terminal

Several steps below ask you to "run a command in the terminal." If you've never used a terminal before, that's fine -- here's the short version:

- The terminal is a text-based way to control your computer. It's already installed on every Mac, Linux machine, and Windows computer. You type commands; the computer runs them.
- To open it:
  - **macOS:** open **Terminal** (it's in **Applications → Utilities**, or press Cmd+Space and type "Terminal")
  - **Linux:** open **Terminal** from your applications menu (the exact name varies by distribution -- Terminal, Console, GNOME Terminal, Konsole)
  - **Windows:** open **Ubuntu** (or whatever WSL2 distribution you installed; see step 1 if you don't have WSL2 yet)
- When this guide shows a code block like:
  ```bash
  some-command
  ```
  ...it means: type that line into the terminal and press Enter.
- "Copy-paste" works in the terminal -- you don't have to type long commands by hand. Right-click and paste, or Cmd/Ctrl+Shift+V depending on your terminal.

You'll keep the same terminal window open through most of this guide. Don't close it until you're done.

## Step 1: Install Docker

GlycemicGPT runs in Docker, which is software that lets you run pre-packaged services on your computer without manually installing each one.

If you don't have Docker yet, see [Install with Docker -- Installing Docker](./install/docker.md#installing-docker) for step-by-step instructions for macOS, Linux, and Windows.

If you already have Docker, type this into your terminal and press Enter:

```bash
docker --version
```

If you see a version number (something like `Docker version 27.x.x`), you're set.

## Step 2: Download GlycemicGPT

In the same terminal window, type each of these commands one at a time and press Enter after each:

```bash
git clone https://github.com/GlycemicGPT/GlycemicGPT.git
cd GlycemicGPT
```

What these commands do:

- `git clone ...` -- downloads all the GlycemicGPT files onto your computer. It creates a folder named `GlycemicGPT` wherever you were when you ran the command. (If you don't have `git` installed, your terminal will say so. To install it: `xcode-select --install` on Mac, `sudo apt install git` on Linux, or download from [git-scm.com](https://git-scm.com) on Windows.)
- `cd GlycemicGPT` -- "change directory" -- moves you into the folder you just downloaded. From here on, every command in this guide should be run from inside this folder unless we say otherwise.

## Step 3: Set up the configuration file

GlycemicGPT reads its settings from a file called `.env`. Copy the template by running this in the same terminal (still inside the `GlycemicGPT` folder):

```bash
cp .env.example .env
```

`cp` means "copy" -- this duplicates `.env.example` (the template that came with the source code) into a new file called `.env` (your actual settings file).

**Trying it locally?** The defaults are fine -- skip ahead to step 4.

**Setting up an always-on deployment?** Open `.env` in a text editor and change at least these values before continuing:

| Variable | What to set it to | Why |
|---|---|---|
| `SECRET_KEY` | A long random string | Used to sign your authentication tokens. Run `openssl rand -hex 32` in a terminal and paste the output. |
| `POSTGRES_PASSWORD` | A strong password you make up | Locks down the database. |
| `COOKIE_SECURE` | `true` | Required when your platform is served over HTTPS (which it should be on a VPS). |
| `CORS_ORIGINS` | `["https://yourdomain.com"]` | The URL where your dashboard will be served. |

The other variables can stay at defaults. In step 8 you'll configure your AI provider from the dashboard (**Settings → AI Provider**), not from `.env`.

## Step 4: Start GlycemicGPT

GlycemicGPT ships several Docker Compose configurations for different scenarios. Pick the one that matches your situation:

| Where you'll run the platform | What you want | Use this |
|---|---|---|
| Your laptop or desktop | Just trying it out, no public access | The root [`docker-compose.yml`](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/docker-compose.yml) (you already have this from `git clone`) |
| **A computer running 24/7 at home, or a small cloud server you rent** | **Public access without opening any ports on your network** | [`deploy/examples/cloudflare-tunnel/`](https://github.com/GlycemicGPT/GlycemicGPT/tree/main/deploy/examples/cloudflare-tunnel) -- works for home or cloud, often the simplest and most secure path |
| A small cloud server you rent (sometimes called a VPS) | Public access with your own domain and automatic HTTPS | [`deploy/examples/public-cloud/`](https://github.com/GlycemicGPT/GlycemicGPT/tree/main/deploy/examples/public-cloud) |
| A home computer with a public IP from your internet provider | You want to handle HTTPS yourself without involving Cloudflare | [`deploy/examples/prod-caddy/`](https://github.com/GlycemicGPT/GlycemicGPT/tree/main/deploy/examples/prod-caddy) |
| Anywhere | You already run your own Redis or Valkey (an in-memory cache) | [`deploy/examples/external-redis/`](https://github.com/GlycemicGPT/GlycemicGPT/tree/main/deploy/examples/external-redis) |

Each example folder has a `README.md` with the start-to-finish walkthrough for that path. Below is a quick reference for the three most common cases. If you're not sure which to pick, the home-server-with-Cloudflare-Tunnel path is the easiest "I want to actually use this day-to-day" option for most users, and the laptop path is the easiest "I want to try it" option.

### Trying it locally on your laptop or desktop

In the same terminal window, still inside the `GlycemicGPT` folder, run:

```bash
docker compose up -d
```

What this does: `docker compose up` reads the recipe in `docker-compose.yml` and starts all the parts GlycemicGPT needs:

- a **database** that stores your data
- a **cache** that speeds up repeat requests
- the **API** that the dashboard and the mobile app talk to
- the **web dashboard** itself (what you'll open in a browser)
- the **AI bridge** that forwards your AI chat messages to whichever AI provider you set up later

The `-d` flag means "run them in the background" so they don't take over your terminal window.

That's it. The platform is running on your computer at `http://localhost:3000`.

The first time you run this, it will take a few minutes to download images and build everything (you'll see a lot of text scrolling by -- that's normal). Subsequent starts are fast. There's no public exposure -- the dashboard is only reachable from your computer.

### Always-on with Cloudflare Tunnel (home server or VPS)

This is the path most users will want for day-to-day use. You run GlycemicGPT on either:

- a computer at home (desktop, NAS, mini-PC, Raspberry Pi -- anything running 24/7), or
- a cloud VPS without opening any inbound ports to the internet.

Cloudflare manages the public access. **No port forwarding, no public IP from your ISP, no inbound firewall rules on your VPS, no TLS certificates to renew.** Your server makes one outbound connection to Cloudflare; all inbound traffic comes through that connection. This is often the simplest path for both home and VPS deployments and is generally more secure than opening ports directly to the internet -- see [Install with Docker -- Why this is often more secure than opening ports](./install/docker.md#why-this-is-often-more-secure-than-opening-ports) for the security rationale.

What you'll need: a [Cloudflare](https://www.cloudflare.com) account (free) and a domain on Cloudflare.

```bash
cd deploy/examples/cloudflare-tunnel/
cp .env.example .env
# Edit .env -- paste your Cloudflare Tunnel token + generate the secrets
docker compose up -d
```

The full walkthrough -- creating the Cloudflare account, adding your domain, creating the tunnel, configuring routing -- is in [Install with Docker -- Deploying with Cloudflare Tunnel](./install/docker.md#deploying-with-cloudflare-tunnel-home-server-or-vps). It's written for non-technical users with no prior Cloudflare experience.

### Running on a cloud VPS with your own domain (Caddy + Let's Encrypt)

This is the path for users who don't have a home server (or don't want to run one) and would rather rent a small cloud server. You get a domain pointing at the server's public IP, Caddy provisions HTTPS automatically via Let's Encrypt.

What you'll need: a VPS from any provider (Hetzner, DigitalOcean, Linode, AWS Lightsail, etc.) and a domain you control.

```bash
cd deploy/examples/public-cloud/
cp .env.example .env
# Edit .env -- set DOMAIN, ACME_EMAIL, and generate the secrets
docker compose up -d
```

The full walkthrough -- DNS setup, firewall, certificate provisioning, troubleshooting -- is in:
- [Install with Docker -- Deploying to a VPS with HTTPS](./install/docker.md#deploying-to-a-vps-with-https) -- the full walkthrough with DNS setup, firewall, certificate provisioning, and troubleshooting

## Step 5: Wait for everything to be ready

In the same terminal, run:

```bash
docker compose ps
```

`docker compose ps` shows the status of each service. You're ready when each service shows `healthy` or `running`. If anything still shows `starting`, wait another 30 seconds and run the command again to check.

## Step 6: Open the dashboard

- **Local:** `http://localhost:3000`
- **Always-on deployment:** the public hostname you configured in step 4 (for example `https://glycemicgpt.yourdomain.com` for a Cloudflare Tunnel subdomain, or `https://yourdomain.com` for a VPS root domain)

You should see the GlycemicGPT login page.

## Step 7: Register an account

Click **Sign up** and create an account with an email and password. Your account stays on your platform -- it does not phone home.

The first time you sign in, you'll see a safety disclaimer. Read it, accept it, and you're at your dashboard.

## Step 8: Configure your AI provider

**GlycemicGPT does not host an AI service.** You bring your own. The platform supports five different ways to plug one in -- you only need to pick one.

### Pick the option that fits you

Most people land here. Read the row that matches you, then jump to that option below:

| If this is you... | Do this | Cost |
|---|---|---|
| **You already pay for Claude (Pro / Max)** | Option 1 | $0 extra (uses your subscription) |
| **You already pay for ChatGPT (Plus / Team)** | Option 2 | $0 extra (uses your subscription) |
| **No subscription, want the easiest cloud option** | Option 3 (Claude API key) | A few cents to a few dollars per month |
| **No subscription, want the cheapest cloud option** | Option 4 (OpenAI API key, cheaper models) | Often under $1 per month |
| **You want everything to stay on your own computer** | Option 5 (local Ollama) | $0, but you need a beefy enough computer |

If you're not sure which to pick, the strongest recommendation for typical users is **Option 1** if you already pay for Claude, otherwise **Option 3**. You can switch at any time from **Settings → AI Provider** without losing data.

For a deeper comparison (privacy, quality, switching), see [BYOAI](./concepts/byoai.md).

### Option 1: Use your existing Claude subscription (Pro / Max)

If you already pay for [Claude](https://claude.ai) (Pro, Max, or Team), you can use that subscription with GlycemicGPT -- you don't need a separate API key. The platform's AI bridge uses a one-time login token from Anthropic's official command-line tool to make calls under your subscription.

You'll need **Node.js** installed on a computer (your laptop is fine -- it doesn't have to be the same computer the platform runs on). If you don't have Node.js: download the LTS version from [nodejs.org](https://nodejs.org) and run the installer.

Once Node.js is installed, open a terminal and run:

```bash
npx @anthropic-ai/claude-code setup-token
```

This opens a browser window where you sign in to your Claude account. After you sign in, the terminal prints a long string of letters and numbers -- that's the token. Copy it.

In the GlycemicGPT dashboard, go to **Settings → AI Provider**, choose **Claude (subscription)**, and paste the token. The AI bridge stores it and uses it for all your AI requests from now on.

> **Heads up on subscription tokens:** The CLI commands above (`claude-code setup-token`, `codex login`) are official, vendor-published tools, but using their tokens from a third-party server (the AI bridge) for ongoing background calls is not a use case Anthropic or OpenAI has publicly endorsed. It works today, but tokens can stop working without notice if a vendor update changes how they're scoped. If you need rock-solid reliability (caregiver alerts, someone else's data flowing through this), use Option 3 or 4 -- direct API keys are explicitly designed for server use. See [BYOAI -- Subscription-token note](./concepts/byoai.md#a-note-on-the-subscription-token-options-options-1-and-2) for the longer discussion.

### Option 2: Use your existing ChatGPT subscription (Plus / Team)

If you already pay for [ChatGPT](https://chat.openai.com) (Plus, Team, or Enterprise), you can use that subscription with GlycemicGPT. Same idea as Claude -- you'll use OpenAI's official command-line tool to get a token.

You'll need Node.js installed (see Option 1 if you don't have it yet). Then run in a terminal:

```bash
npx @openai/codex login
```

A browser window opens for you to sign in to your OpenAI account. The terminal then prints a token. Copy it, then paste it into the GlycemicGPT dashboard at **Settings → AI Provider → ChatGPT (subscription)**.

### Option 3: Bring your own Claude API key

If you'd rather pay per token directly to Anthropic instead of via a subscription:

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Sign up or sign in
3. Go to **API Keys**, create a new key
4. Copy the key (starts with `sk-ant-...`)
5. In GlycemicGPT, **Settings → AI Provider → Claude (API key)**, paste the key

You'll be billed by Anthropic per request. Lower fixed cost than a subscription, higher per-message cost.

### Option 4: Bring your own OpenAI API key

Same flow for OpenAI:

1. Go to [platform.openai.com](https://platform.openai.com)
2. Sign in
3. **API keys** → create new
4. Copy the key (starts with `sk-...`)
5. In GlycemicGPT, **Settings → AI Provider → OpenAI (API key)**, paste the key

### Option 5: Run a local model with Ollama (or any OpenAI-compatible endpoint)

If you want to keep AI fully local -- nothing leaves your network -- run an Ollama server and point GlycemicGPT at it.

1. Install [Ollama](https://ollama.com) on your computer or server
2. Pull a model: `ollama pull llama3.1:8b` (or any model you prefer)
3. Make sure Ollama is reachable from where the platform runs (default: `http://localhost:11434`)
4. In GlycemicGPT, **Settings → AI Provider → OpenAI-compatible**, set:
   - **Base URL:** `http://localhost:11434/v1` (or wherever your Ollama instance is)
   - **Model name:** the model you pulled (e.g. `llama3.1:8b`)
   - **API key:** any non-empty string -- Ollama doesn't check it but the field is required

This same option works for any OpenAI-compatible endpoint: LM Studio, vLLM, llama.cpp's server mode, OpenRouter, Together, Groq, etc.

### Switching providers later

You can change providers anytime in **Settings → AI Provider**. Your data stays where it is; the platform just starts routing AI calls to the new provider.

## Step 9: Install the mobile app

**The Android app is required** to connect your pump and read its data. The platform alone cannot do this -- the phone app handles the Bluetooth connection.

See [Mobile app install](./mobile/install.md) for the step-by-step Android install (about 10-15 minutes). The short version:

1. Go to [GlycemicGPT releases on GitHub](https://github.com/GlycemicGPT/GlycemicGPT/releases)
2. Download the latest `app-release.apk`
3. On your phone, open the file and install it (you'll need to allow installs from unknown sources)
4. Open the app, point it at your platform's URL (local: your computer's IP; always-on deployment: your domain), and sign in with the account you just created

Once the app is signed in and your pump is paired, your dashboard fills with data.

## Step 10 (optional): Install the watch face

A Wear OS watch face is available for at-a-glance glucose viewing. **It's optional** -- the platform and phone app give you everything important without it.

Heads up: setting up the watch face is more involved than the rest of this guide. It requires connecting your watch to a computer over a developer connection (called ADB) to install the watch face directly, since the watch face is not on the Play Store yet.

See [Watch face install](./mobile/wear-os.md) for the full procedure.

## What's next?

You can now:

- Open the dashboard and watch glucose flow in
- Ask the AI a question about your data ("how did I do overnight?", "what patterns do you see this week?")
- Set up alerts so the platform tells you when something needs attention
- Invite a family member or other trusted person as a caregiver
- Print a Time-in-Range summary to bring to your next endocrinologist appointment

Where to go from here:

- **Connect your CGM** -- [Connecting your Dexcom](./daily-use/connecting-dexcom.md)
- **Connect your pump (cloud)** -- [Connecting your Tandem pump](./daily-use/connecting-tandem-cloud.md)
- **Read your dashboard** -- [Reading your dashboard](./daily-use/dashboard.md)
- **Set up alerts** -- [Configuring alerts](./daily-use/alerts.md)
- **Invite a caregiver** -- [Caregivers overview](./caregivers/overview.md)
- **Need more detail on Docker?** -- [Install with Docker](./install/docker.md)
- **Something not working?** -- [Troubleshooting](./troubleshooting/index.md)

## A few honest reminders

- **GlycemicGPT is alpha software.** It works, but it has not been broadly tested. Treat it as a tool that supplements your existing diabetes management, not as a replacement for it.
- **GlycemicGPT does not control insulin delivery.** It reads from your devices; it does not write back to them.
- **AI suggestions are not medical advice.** When the AI tells you something interesting, talk to your endocrinologist before acting on it.
- **Your data stays with you.** GlycemicGPT does not phone home or send your data anywhere. The AI provider you choose to use will see the messages you send through the chat interface, just like any other AI service.
