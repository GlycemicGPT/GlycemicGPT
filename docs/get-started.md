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
| Plan to use it day-to-day with your phone reaching it from anywhere | **Always-on deployment** -- a VPS, home server, or any computer running 24/7 |

You can always start locally and migrate to an always-on setup later -- your settings and data live in the database, and the platform itself is the same.

> **Before you start, you need:**
>
> - **A computer to run the platform on** -- a laptop, desktop, home server, or VPS. Resource recommendations:
>   - **RAM:** 2 GB minimum, 4 GB recommended. The API service loads an embedding model that uses ~1 GB by itself; the rest of the stack is light.
>   - **Disk:** 5 GB minimum, 10 GB recommended. Container images are about 3 GB; database, cache, and embedding model storage grow over time.
>   - **CPU:** any modern dual-core works. The platform is mostly idle except during AI requests.
>   - **OS:** macOS, Linux, or Windows with WSL2.
> - **An Android phone** for the companion app (required to connect your pump over Bluetooth)

## Step 1: Install Docker

GlycemicGPT runs in Docker, which is software that lets you run pre-packaged services on your computer without manually installing each one.

If you don't have Docker yet, see [Install with Docker -- Installing Docker](./install/docker.md#installing-docker) for step-by-step instructions for macOS, Linux, and Windows.

If you already have Docker, run `docker --version` in a terminal to confirm. If you see a version number, you're set.

## Step 2: Download GlycemicGPT

Open a terminal and run:

```bash
git clone https://github.com/GlycemicGPT/GlycemicGPT.git
cd GlycemicGPT
```

This creates a `GlycemicGPT` folder on your computer with everything you need.

## Step 3: Set up the configuration file

GlycemicGPT reads its settings from a file called `.env`. Copy the template:

```bash
cp .env.example .env
```

**Trying it locally?** The defaults are fine -- skip ahead to step 4.

**Setting up an always-on deployment?** Open `.env` in a text editor and change at least these values before continuing:

| Variable | What to set it to | Why |
|---|---|---|
| `SECRET_KEY` | A long random string | Used to sign your authentication tokens. Run `openssl rand -hex 32` in a terminal and paste the output. |
| `POSTGRES_PASSWORD` | A strong password you make up | Locks down the database. |
| `COOKIE_SECURE` | `true` | Required when your platform is served over HTTPS (which it should be on a VPS). |
| `CORS_ORIGINS` | `["https://yourdomain.com"]` | The URL where your dashboard will be served. |

The other variables can stay at defaults. You'll come back to `.env` to configure your AI provider in step 8.

## Step 4: Start GlycemicGPT

### Trying it locally

```bash
docker compose up -d
```

That's it. The platform is running on your computer at `http://localhost:3000`.

The first time you run this, it will take a few minutes to download images and build everything. Subsequent starts are fast.

### Setting up an always-on deployment

The plain `docker compose up -d` works on a server too, but it doesn't give you HTTPS or expose the platform to the internet safely. For an always-on deployment with public access, use the public-cloud example, which includes a reverse proxy with automatic HTTPS:

```bash
cd deploy/examples/public-cloud/
cp .env.example .env
# Edit .env -- set DOMAIN, EMAIL, and the same SECRET_KEY / POSTGRES_PASSWORD as before
docker compose up -d
```

Point your domain's DNS at your VPS's IP address (an `A` record), give it a couple minutes for the SSL certificate to provision, and you'll have HTTPS working at `https://yourdomain.com`.

The detailed cloud deployment walkthrough is in [Install with Docker -- Deploying to a VPS with HTTPS](./install/docker.md#deploying-to-a-vps-with-https).

## Step 5: Wait for everything to be ready

```bash
docker compose ps
```

You're ready when each service shows `healthy` or `running`. If anything still shows `starting`, wait another 30 seconds and check again.

## Step 6: Open the dashboard

- **Local:** `http://localhost:3000`
- **Always-on deployment:** `https://yourdomain.com` (the domain you set in step 3)

You should see the GlycemicGPT login page.

## Step 7: Register an account

Click **Sign up** and create an account with an email and password. Your account stays on your platform -- it does not phone home.

The first time you sign in, you'll see a safety disclaimer. Read it, accept it, and you're at your dashboard.

## Step 8: Configure your AI provider

**GlycemicGPT does not host an AI service.** You bring your own. The platform supports five different ways to plug AI in, so you can use whichever you already pay for (or run yourself). Pick one and configure it in the dashboard at **Settings → AI Provider**.

### Option 1: Use your existing Claude subscription (Pro / Max)

If you already pay for [Claude](https://claude.ai) (Pro, Max, or Team), you can use that subscription with GlycemicGPT -- you don't need a separate API key. The sidecar service uses an OAuth token from the official Claude Code CLI to make calls under your subscription.

On any computer (your laptop is fine), with Node.js installed, run:

```bash
npx @anthropic-ai/claude-code setup-token
```

This opens a browser for you to sign in to your Claude account, then prints a long token to your terminal. Copy the token.

In the GlycemicGPT dashboard, go to **Settings → AI Provider**, choose **Claude (subscription)**, and paste the token. The sidecar stores it and uses it for all AI calls.

### Option 2: Use your existing ChatGPT subscription (Plus / Team)

If you already pay for [ChatGPT](https://chat.openai.com) (Plus, Team, or Enterprise), you can use that subscription via the OpenAI Codex CLI. Same idea as Claude:

```bash
npx @openai/codex login
```

Sign in to your OpenAI account in the browser, copy the token it prints, paste it into the GlycemicGPT dashboard at **Settings → AI Provider → ChatGPT (subscription)**.

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

A Wear OS watch face is available for at-a-glance glucose viewing. **It's optional.** Setup is more involved -- it requires a computer to sideload the watch APK because it isn't on the Play Store yet.

See [Watch face install](./mobile/wear-os.md) for the procedure (about 30-60 minutes).

## What's next?

- **Connect your CGM** -- coming soon in [Daily Use](./daily-use/connecting-dexcom.md)
- **Connect your pump** -- coming soon in [Daily Use](./daily-use/connecting-tandem-cloud.md)
- **Use the full Docker reference** -- [Install with Docker](./install/docker.md)
- **Something not working?** -- [Troubleshooting](./troubleshooting/index.md)

## A few honest reminders

- **GlycemicGPT is alpha software.** It works, but it has not been broadly tested. Treat it as a tool that supplements your existing diabetes management, not as a replacement for it.
- **GlycemicGPT does not control insulin delivery.** It reads from your devices; it does not write back to them.
- **AI suggestions are not medical advice.** When the AI tells you something interesting, talk to your endocrinologist before acting on it.
- **Your data stays with you.** GlycemicGPT does not phone home or send your data anywhere. The AI provider you choose to use will see the messages you send through the chat interface, just like any other AI service.
