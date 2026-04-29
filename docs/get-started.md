---
title: Get Started
description: From zero to a working GlycemicGPT setup -- platform, mobile app, and (optionally) the watch face.
---

This guide walks you through setting up GlycemicGPT end-to-end: the platform itself, the Android companion app you need to connect your pump, and the optional watch face.

> **Realistic timing:**
>
> - **Laptop quickstart** (just trying it out): 30-45 minutes
> - **Cloud VPS deployment** (the long-term setup): 1-2 hours
> - **Plus mobile app install:** another 10-15 minutes
> - **Plus watch face install (optional):** another 30-60 minutes

## Pick your path

You can run GlycemicGPT in two ways:

| If you... | Choose this path |
|---|---|
| Want to try it out before committing to anything | **Laptop quickstart** |
| Plan to use it day-to-day with your phone reaching it from anywhere | **Cloud VPS** |

You can always start with the laptop path and migrate to a VPS later -- your settings and data live in the database, and the platform itself is the same.

> **Before you start, you need:**
>
> - A computer or VPS to run the platform on
> - An Android phone (the companion app is required to connect your pump)
> - About **5 GB of free disk space** on the computer running the platform
> - Time: **30-45 minutes** for the laptop path or **1-2 hours** for the VPS path
>
> The platform runs on macOS, Linux, and Windows with WSL2.

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

**For the laptop path:** the defaults are fine -- skip ahead to step 4.

**For the cloud VPS path:** open `.env` in a text editor and change at least these values:

| Variable | What to set it to | Why |
|---|---|---|
| `SECRET_KEY` | A long random string | Used to sign your authentication tokens. Run `openssl rand -hex 32` in a terminal and paste the output. |
| `POSTGRES_PASSWORD` | A strong password you make up | Locks down the database. |
| `COOKIE_SECURE` | `true` | Required when your platform is served over HTTPS (which it should be on a VPS). |
| `CORS_ORIGINS` | `["https://yourdomain.com"]` | The URL where your dashboard will be served. |

The other variables can stay at defaults. You'll come back to `.env` to configure your AI provider in step 8.

## Step 4: Start GlycemicGPT

### Laptop path

```bash
docker compose up -d
```

That's it. The platform is running on your computer at `http://localhost:3000`.

The first time you run this, it will take a few minutes to download images and build everything. Subsequent starts are fast.

### Cloud VPS path

The plain `docker compose up -d` works on a VPS too, but it doesn't give you HTTPS or expose the platform to the internet safely. For a real VPS deployment, use the public-cloud example, which includes a reverse proxy with automatic HTTPS:

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

- **Laptop path:** `http://localhost:3000`
- **Cloud VPS path:** `https://yourdomain.com` (the domain you set in step 3)

You should see the GlycemicGPT login page.

## Step 7: Register an account

Click **Sign up** and create an account with an email and password. Your account stays on your platform -- it does not phone home.

The first time you sign in, you'll see a safety disclaimer. Read it, accept it, and you're at your dashboard.

## Step 8: Configure your AI provider

GlycemicGPT does not bundle an AI provider -- you bring your own. In the dashboard, go to **Settings → AI Provider** and choose one of:

- **Claude** -- paste an API key from [console.anthropic.com](https://console.anthropic.com)
- **OpenAI** -- paste an API key from [platform.openai.com](https://platform.openai.com)
- **Ollama** (fully local, no internet required) -- point at your local Ollama server
- **Subscription tier** -- use the project's hosted AI service (when available)

You can switch providers later. Detailed AI provider configuration is *coming soon*.

## Step 9: Install the mobile app

**The Android app is required** to connect your pump and read its data. The platform alone cannot do this -- the phone app handles the Bluetooth connection.

See [Mobile app install](./mobile/install.md) for the step-by-step Android install (about 10-15 minutes). The short version:

1. Go to [GlycemicGPT releases on GitHub](https://github.com/GlycemicGPT/GlycemicGPT/releases)
2. Download the latest `app-release.apk`
3. On your phone, open the file and install it (you'll need to allow installs from unknown sources)
4. Open the app, point it at your platform's URL (laptop path: your computer's IP; VPS path: your domain), and sign in with the account you just created

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
