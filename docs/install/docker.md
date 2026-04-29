---
title: Install with Docker
description: The full Docker reference for self-hosting GlycemicGPT, including how to install Docker.
---

This is the full reference for running GlycemicGPT with Docker. If you just want the fastest path, see [Get Started](../get-started.md) -- it walks you through the same content as a numbered checklist.

## What is Docker, and why does GlycemicGPT use it?

Docker is software that lets you run pre-packaged services on your computer or server without manually installing each one. Instead of installing PostgreSQL, Redis, Python, Node.js, and configuring them all to talk to each other, you run one command (`docker compose up`) and Docker takes care of the rest.

GlycemicGPT uses Docker because it makes the platform easy to install (one command), easy to update (one command), and identical across macOS, Linux, and Windows. You don't need to know how Docker works internally to use it -- you just need it installed.

## Installing Docker

### macOS

1. Go to [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
2. Click **Download for Mac** -- choose the right chip type:
   - Apple Silicon (M1, M2, M3, M4) -- the "Apple Silicon" download
   - Intel Mac -- the "Intel chip" download
3. Open the downloaded `.dmg` file
4. Drag Docker into your Applications folder
5. Open Docker from Applications. The first launch takes a minute -- wait until you see the Docker whale icon in your menu bar.
6. Confirm it's working. Open Terminal (in Applications → Utilities) and run:
   ```bash
   docker --version
   ```
   If you see a version number (e.g. `Docker version 27.x.x`), you're set.

### Windows (WSL2 required)

GlycemicGPT runs on Windows through WSL2 (Windows Subsystem for Linux). If you've never set up WSL2 before, follow Microsoft's [WSL install guide](https://learn.microsoft.com/en-us/windows/wsl/install) first.

Once WSL2 is working:

1. Go to [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
2. Click **Download for Windows**
3. Run the installer. When asked, ensure "Use WSL 2 instead of Hyper-V" is checked.
4. Reboot if prompted.
5. Open Docker Desktop. In Settings → Resources → WSL Integration, enable integration with your WSL2 distribution (usually Ubuntu).
6. Open your WSL2 terminal and run:
   ```bash
   docker --version
   ```
   If you see a version number, you're set.

### Linux

The easiest way is the official convenience script:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

Log out and back in (so your user picks up the `docker` group), then verify:

```bash
docker --version
docker compose version
```

For a manual install or specific distro instructions, see the [Docker Engine install guide](https://docs.docker.com/engine/install/).

## Which Docker setup is right for you?

GlycemicGPT ships several Docker Compose configurations for different scenarios. Pick the one that matches how you'll use the platform:

| If you want to... | Use this | TLS / HTTPS | Notes |
|---|---|---|---|
| Try it on a single computer at home (laptop, desktop, NAS, etc.) | The root [`docker-compose.yml`](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/docker-compose.yml) | Not needed | Simplest path. Runs everything locally. This is what [Get Started](../get-started.md) walks through. |
| Deploy on a VPS with a public domain | [`deploy/examples/public-cloud/`](https://github.com/GlycemicGPT/GlycemicGPT/tree/main/deploy/examples/public-cloud) | Caddy with Let's Encrypt (automatic) | **Recommended for cloud deployments.** Single `.env` file to fill in, automatic HTTPS, sane security defaults. |
| Run behind Cloudflare with zero exposed ports | [`deploy/examples/cloudflare-tunnel/`](https://github.com/GlycemicGPT/GlycemicGPT/tree/main/deploy/examples/cloudflare-tunnel) | Cloudflare-managed | If you already use Cloudflare. No inbound ports open. |
| Use your own Redis or Valkey cluster | [`deploy/examples/external-redis/`](https://github.com/GlycemicGPT/GlycemicGPT/tree/main/deploy/examples/external-redis) | Bring your own proxy | For users with existing Redis infrastructure. |
| Use pre-built images and bring your own reverse proxy | [`docker-compose.prod.yml`](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/docker-compose.prod.yml) | Bring your own proxy | If you already run nginx, Traefik, etc. |

## The five services

Whichever setup you use, GlycemicGPT runs five services:

- **`web`** -- The dashboard you visit in your browser. Serves on port 3000 locally, or proxied through HTTPS on an always-on deployment.
- **`api`** -- The backend that handles your data, settings, and account. Serves on port 8000 locally, or proxied internally on an always-on deployment.
- **`sidecar`** -- The AI relay. When you chat with the AI, your message goes here, then to your AI provider, then back to you. Internal-only.
- **`db`** -- A PostgreSQL database. This is where your data is stored. Internal-only.
- **`redis`** -- A cache for sessions and real-time updates. Internal-only.

## Configuration: the `.env` file

Most of GlycemicGPT's behavior is controlled by environment variables in the `.env` file. The defaults work for trying it on a local computer; you'll change a few when deploying anywhere that's reachable from outside your machine.

### Variables you must change for any always-on deployment

- **`SECRET_KEY`** -- Used to sign authentication tokens. Generate a new value with `openssl rand -hex 32`.
- **`POSTGRES_PASSWORD`** -- Database password. Generate a new value with `openssl rand -hex 32`.
- **`REDIS_PASSWORD`** -- Redis password (the public-cloud example requires one). Generate with `openssl rand -hex 32`.
- **`COOKIE_SECURE`** -- Set to `true` when your platform is served over HTTPS.
- **`CORS_ORIGINS`** -- A list of URLs where your dashboard will be served from. The public-cloud example sets this automatically from your `DOMAIN`.

### Variables that usually stay default

`DATABASE_URL`, `REDIS_URL`, `POSTGRES_USER`, `POSTGRES_DB` -- the defaults reference the bundled containers and work out of the box.

### AI provider

GlycemicGPT does not host an AI service -- you bring your own. After you sign in to the dashboard, go to **Settings → AI Provider** and pick one of:

- **Your existing Claude subscription** (Pro / Max) -- get a token via `npx @anthropic-ai/claude-code setup-token` and paste it
- **Your existing ChatGPT subscription** (Plus / Team) -- get a token via `npx @openai/codex login` and paste it
- **Your own Claude API key** -- pay-per-token directly to Anthropic, key from [console.anthropic.com](https://console.anthropic.com)
- **Your own OpenAI API key** -- pay-per-token, key from [platform.openai.com](https://platform.openai.com)
- **A local model via Ollama** (or any OpenAI-compatible endpoint) -- fully offline, point at your Ollama server

See [Get Started -- Step 8: Configure your AI provider](../get-started.md#step-8-configure-your-ai-provider) for the per-provider walkthrough.

## Common operations

### Start everything

```bash
docker compose up -d
```

The `-d` runs in the background. To watch logs as you start, omit `-d`.

### Stop everything (keep data)

```bash
docker compose down
```

Your database and configuration are preserved. Run `docker compose up -d` again to resume where you left off.

### Stop everything and delete data

```bash
docker compose down -v
```

> **The `-v` flag deletes your database.** Only use this if you want a fresh start.

### Watch the logs

```bash
docker compose logs -f api
```

Replace `api` with `web`, `sidecar`, `db`, or `redis` to watch other services. Without a name, you see all services together.

### Update to a new release

For trying it locally / development:

```bash
git pull
docker compose up -d --build
```

For the public-cloud example (uses prebuilt images):

```bash
docker compose pull
docker compose up -d
```

The `:latest` tag pulls whatever the most recent stable release is.

## Deploying to a VPS with HTTPS

This is the recommended path for running GlycemicGPT day-to-day. It gets you HTTPS, a real domain, and lets your mobile app reach the platform from anywhere.

### What you'll need

- A VPS or cloud server (Hetzner, DigitalOcean, Linode, OVH, AWS Lightsail -- any provider works)
- Docker installed on the server (see [Installing Docker](#installing-docker) above)
- A domain name and DNS access to point it at your server
- About 1-2 hours

### 1. Set up DNS

In your domain registrar's DNS settings, add an `A` record:

```
glycemicgpt.example.com    A    <your server's public IP>
```

DNS propagation usually takes a few seconds to an hour. Check it's working:

```bash
dig +short yourdomain.com
```

If you see your server's IP, DNS is ready.

### 2. Open ports 80 and 443

Caddy needs both to provision a Let's Encrypt certificate and serve traffic. If your VPS provider has a firewall, allow inbound TCP on both.

### 3. Clone GlycemicGPT on the server

```bash
git clone https://github.com/GlycemicGPT/GlycemicGPT.git
cd GlycemicGPT/deploy/examples/public-cloud/
```

### 4. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env` and set:

| Variable | What to put |
|---|---|
| `DOMAIN` | Your domain (e.g. `glycemicgpt.example.com`) |
| `ACME_EMAIL` | A real email -- you'll get cert expiry notices |
| `POSTGRES_PASSWORD` | Run `openssl rand -hex 32`, paste output |
| `REDIS_PASSWORD` | Run `openssl rand -hex 32`, paste output |
| `SECRET_KEY` | Run `openssl rand -hex 32`, paste output |

Leave the other variables at their defaults.

### 5. Start everything

```bash
docker compose up -d
```

This pulls the prebuilt GlycemicGPT images from GitHub Container Registry, starts all five services, and triggers Caddy to request a Let's Encrypt certificate.

### 6. Wait for the certificate

Caddy provisions your TLS certificate on first request. Usually 30-60 seconds. Watch:

```bash
docker compose logs -f caddy
```

When you see `certificate obtained successfully`, you're ready.

### 7. Open your dashboard

Visit `https://yourdomain.com`. You should see the GlycemicGPT login page over HTTPS.

### What's exposed?

Only ports 80 and 443. The database, Redis, API, web, and sidecar are all on an internal Docker network -- not reachable from outside the server.

For the deployment-specific reference, see [`deploy/examples/public-cloud/README.md`](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/deploy/examples/public-cloud/README.md).

## Connecting devices

Once you're signed in, you can connect your devices in the dashboard's settings:

- **Dexcom G7** -- Cloud API. You'll provide your Dexcom Share account credentials.
- **Tandem t:slim X2** -- Two paths:
  - **Cloud (t:connect)** -- You'll provide your Tandem account credentials. The cloud syncs every ~60 minutes.
  - **BLE direct** -- Real-time data via Bluetooth. Requires the [GlycemicGPT mobile app](../mobile/install.md).

Detailed device-connection walkthroughs are in [Daily Use](../daily-use/connecting-dexcom.md).

## When to use Kubernetes instead

Docker Compose is the right choice for most users. Use Kubernetes only if you already run a homelab or production Kubernetes cluster and prefer to deploy GlycemicGPT alongside your other workloads. See [Install with Kubernetes](./kubernetes.md).

A one-click managed deploy (Railway, Fly.io) is on the roadmap -- see [ROADMAP.md](../../ROADMAP.md) §Phase 4.

## Troubleshooting

If something isn't working, see [Troubleshooting](../troubleshooting/index.md). The most common starting points:

- Dashboard won't load → check `docker compose ps` for unhealthy services
- Glucose isn't updating → check device connection in dashboard settings
- AI chat isn't responding → check the sidecar service is running and your AI provider is configured
- Caddy can't get a certificate → DNS not pointing at the server, or ports 80/443 blocked
