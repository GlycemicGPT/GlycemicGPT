# Cloudflare Tunnel deployment

This directory contains the Docker Compose configuration for deploying GlycemicGPT behind a Cloudflare Tunnel -- public access without opening any inbound ports on your server.

**Files:**

- `docker-compose.yml` -- the compose stack: GlycemicGPT services + a cloudflared connector
- `.env.example` -- template for required environment variables (Cloudflare tunnel token, database passwords, secret key)

## Full walkthrough

The complete step-by-step guide -- creating the Cloudflare account, adding your domain, creating the tunnel, configuring DNS routing, starting the stack, and troubleshooting -- is in the project's docs:

**[Install with Docker -- Deploying with Cloudflare Tunnel](../../../docs/install/docker.md#deploying-with-cloudflare-tunnel-home-server-or-vps)**

That guide is written for non-technical users with no prior Cloudflare experience. It works equally well for home servers and cloud VPS deployments.

## Quick start (for users who already know the drill)

```bash
cp .env.example .env
# Edit .env: paste CLOUDFLARE_TUNNEL_TOKEN, generate POSTGRES_PASSWORD,
# REDIS_PASSWORD, and SECRET_KEY with: openssl rand -hex 32
docker compose up -d
```

Then watch the cloudflared logs to confirm the tunnel registered:

```bash
docker compose logs -f cloudflared
```

When you see `Connection registered`, visit `https://yoursubdomain.yourdomain.com`.

## When to use this vs other examples

- **Use this** -- you want public access without exposing any inbound ports (home server or VPS, the simpler and often more secure path)
- **Use [`../public-cloud/`](../public-cloud/)** -- you want a VPS deployment with your own reverse proxy (Caddy + Let's Encrypt), no Cloudflare in the data path
- **Use [`../prod-caddy/`](../prod-caddy/)** -- minimal Caddy example with manual Caddyfile editing
- **Use [`../external-redis/`](../external-redis/)** -- you have an existing Redis or Valkey cluster to reuse
- **Use the [root `docker-compose.yml`](../../../docker-compose.yml)** -- local development on your own computer (no public access)
