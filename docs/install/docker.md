---
title: Install with Docker
description: Choose the Docker setup that fits how you'll use GlycemicGPT.
---

Docker Compose is the recommended way to run GlycemicGPT for most users. This page is the full reference -- if you just want the fastest path, see [Get Started](../get-started.md).

> **Before you start, you need:**
> - **Docker Engine and Docker Compose** (or Docker Desktop on macOS / Windows)
> - About **5 GB of free disk space**
> - **Ports 3000, 8000, 3456, 5432, 6379** free, or be willing to remap them in the compose file

## Which setup is right for you?

We ship several Docker Compose configurations for different scenarios. Pick the one that matches how you'll use GlycemicGPT:

| If you want to... | Use this | TLS / HTTPS | Notes |
|---|---|---|---|
| Try it on your laptop or a single computer at home | The root [`docker-compose.yml`](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/docker-compose.yml) | Not needed | The simplest path. Runs everything locally. This is what [Get Started](../get-started.md) walks through. |
| Run on a server with your own domain and automatic HTTPS | [`deploy/examples/prod-caddy/`](https://github.com/GlycemicGPT/GlycemicGPT/tree/main/deploy/examples/prod-caddy) | Caddy with Let's Encrypt (automatic) | Recommended for most users running on a server. Caddy handles HTTPS for you -- no manual cert management. |
| Run behind Cloudflare with zero exposed ports | [`deploy/examples/cloudflare-tunnel/`](https://github.com/GlycemicGPT/GlycemicGPT/tree/main/deploy/examples/cloudflare-tunnel) | Cloudflare-managed | If you already use Cloudflare. Your server has no inbound ports open at all. |
| Use your own Redis or Valkey cluster instead of the bundled one | [`deploy/examples/external-redis/`](https://github.com/GlycemicGPT/GlycemicGPT/tree/main/deploy/examples/external-redis) | Bring your own proxy | For users with existing Redis infrastructure. |
| Use pre-built images from GitHub Container Registry instead of building locally | [`docker-compose.prod.yml`](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/docker-compose.prod.yml) | Bring your own proxy | Faster startup. You manage the reverse proxy yourself. |

## The five services

Whichever setup you use, GlycemicGPT runs five services:

- **`web`** -- The dashboard you visit in your browser. Listens on port 3000.
- **`api`** -- The backend that handles your data, settings, and account. Listens on port 8000.
- **`sidecar`** -- The AI relay. When you chat with the AI, your message goes here, then to your AI provider, then back to you. Listens on port 3456.
- **`db`** -- A PostgreSQL database. Listens on port 5432. This is where your data is stored.
- **`redis`** -- A cache for sessions and real-time updates. Listens on port 6379.

## Configuration: the `.env` file

Most of GlycemicGPT's behavior is controlled by environment variables in the `.env` file. The defaults work for local use; you'll change a few when deploying to a server.

### Variables you'll likely change

- **`SECRET_KEY`** -- Used to sign authentication tokens. **Change this for any deployment that's not just on your laptop.** Generate a new value with `openssl rand -hex 32`.
- **`POSTGRES_PASSWORD`** -- Database password. Change for production deployments.
- **`COOKIE_SECURE`** -- Set to `true` when you have HTTPS configured. The dev override sets it to `false` for local use.
- **`CORS_ORIGINS`** -- A list of URLs your frontend will be served from. Add your domain when deploying.

### Variables that usually stay default

`DATABASE_URL`, `REDIS_URL`, `POSTGRES_USER`, `POSTGRES_DB` -- the defaults reference the bundled containers and work out of the box.

### AI provider

GlycemicGPT does not bundle an AI provider. You bring your own:

- **Subscription tier** -- use the project's hosted AI service (when available)
- **Bring your own key** -- plug in your own Claude, OpenAI, Ollama, or any OpenAI-compatible endpoint

You configure this in the dashboard once you're signed in. AI provider configuration documentation is *coming soon*.

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

```bash
git pull
docker compose up -d --build
```

This pulls the latest code, rebuilds anything that changed, and restarts services that need it.

## Connecting devices

Once you're signed in, you can connect your devices in the dashboard's settings:

- **Dexcom G7** -- Cloud API. You'll provide your Dexcom Share account credentials.
- **Tandem t:slim X2 / Mobi** -- Two paths:
  - **Cloud (t:connect)** -- You'll provide your Tandem account credentials. The cloud syncs every ~60 minutes.
  - **BLE direct** -- Real-time data via Bluetooth. Requires the GlycemicGPT mobile app. *(Mobile docs coming soon.)*

Detailed device-connection walkthroughs are in [Daily Use](../daily-use/connecting-dexcom.md).

## When to use Kubernetes instead

Docker Compose is the right choice for most users. Use Kubernetes only if you already run a homelab or production Kubernetes cluster and prefer to deploy GlycemicGPT alongside your other workloads. See [Install with Kubernetes](./kubernetes.md).

A one-click cloud deploy (Railway, Fly.io) is on the roadmap -- see [ROADMAP.md](../../ROADMAP.md) §Phase 4.

## Troubleshooting

If something isn't working, see [Troubleshooting](../troubleshooting/index.md). The most common starting points:

- Dashboard won't load → check `docker compose ps` for unhealthy services
- Glucose isn't updating → check device connection in dashboard settings
- AI chat isn't responding → check the sidecar service is running and your AI provider is configured
