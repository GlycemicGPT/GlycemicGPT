# Public cloud deployment with Caddy + Let's Encrypt

This directory contains the Docker Compose configuration for a VPS deployment of GlycemicGPT with automatic HTTPS via Caddy and Let's Encrypt.

**Files:**

- `docker-compose.yml` -- the compose stack: GlycemicGPT services + Caddy reverse proxy
- `Caddyfile` -- env-driven Caddy config (reads `${DOMAIN}` and `${ACME_EMAIL}` from `.env`)
- `.env.example` -- template for required environment variables

## Full walkthrough

The complete step-by-step guide -- DNS setup, firewall, certificate provisioning, troubleshooting -- is in the project's docs:

**[Install with Docker -- Deploying to a VPS with HTTPS](../../../docs/install/docker.md#deploying-to-a-vps-with-https)**

That guide also covers Docker installation, `.env` hardening for any non-laptop deployment, common operations (start, stop, logs, update), and the broader picture of how this fits with the other deployment examples.

## Quick start (for users who already know the drill)

```bash
cp .env.example .env
# Edit .env: set DOMAIN, ACME_EMAIL, and generate POSTGRES_PASSWORD,
# REDIS_PASSWORD, and SECRET_KEY with: openssl rand -hex 32
docker compose up -d
```

Then watch the Caddy logs to confirm the certificate provisioned:

```bash
docker compose logs -f caddy
```

When you see `certificate obtained successfully`, visit `https://yourdomain.com`.

## When to use this vs other examples

- **Use this** -- you have a VPS with a public IP and want a reverse proxy with automatic HTTPS that you control (no third party in the data path)
- **Use [`../cloudflare-tunnel/`](../cloudflare-tunnel/)** -- you want public access without opening any inbound ports (often simpler and more secure; works for home or VPS)
- **Use [`../prod-caddy/`](../prod-caddy/)** -- minimal Caddy example with manual Caddyfile editing (this example supersedes it for most users)
- **Use [`../external-redis/`](../external-redis/)** -- you have an existing Redis or Valkey cluster to reuse
- **Use the [root `docker-compose.yml`](../../../docker-compose.yml)** -- local development on your own computer (no public access)
