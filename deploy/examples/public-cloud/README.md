# Public cloud deployment with automatic HTTPS

This is the recommended setup for running GlycemicGPT on a VPS or cloud instance with a public domain. It bundles the GlycemicGPT services with Caddy as a reverse proxy that automatically provisions Let's Encrypt TLS certificates.

**One file to edit (`.env`), one command to run (`docker compose up -d`).**

## What you'll need

- A VPS or cloud server (any provider -- Hetzner, DigitalOcean, Linode, OVH, AWS Lightsail, etc.)
- Docker and Docker Compose installed on the server
- A domain name (e.g. `glycemicgpt.example.com`)
- DNS access to point the domain at your server

## Steps

### 1. Point your domain at the server

Create an `A` record for your domain pointing at the server's public IP address.

DNS propagation can take anywhere from a few seconds to an hour. Check it's working with:

```bash
dig +short yourdomain.com
```

If you see your server's IP, you're set.

### 2. Make sure ports 80 and 443 are open

Caddy needs ports 80 and 443 to provision the Let's Encrypt certificate and serve traffic. If your VPS provider has a firewall, allow inbound TCP traffic on both.

### 3. Copy the configuration template

```bash
cd deploy/examples/public-cloud/
cp .env.example .env
```

### 4. Fill in the required values

Open `.env` in your editor and set these:

| Variable | What to put |
|---|---|
| `DOMAIN` | Your domain (e.g. `glycemicgpt.example.com`) |
| `ACME_EMAIL` | A real email -- you'll get cert expiry notices |
| `POSTGRES_PASSWORD` | Run `openssl rand -hex 32`, paste output |
| `REDIS_PASSWORD` | Run `openssl rand -hex 32`, paste output |
| `SECRET_KEY` | Run `openssl rand -hex 32`, paste output |

Leave everything else at its default unless you have a specific reason to change it.

### 5. Start everything

```bash
docker compose up -d
```

This pulls the prebuilt GlycemicGPT images from GitHub Container Registry, starts all services, and triggers Caddy to request a Let's Encrypt certificate.

### 6. Wait for the certificate

Caddy provisions your TLS certificate automatically on first request. This usually takes 30-60 seconds. Watch the Caddy logs:

```bash
docker compose logs -f caddy
```

When you see something like `certificate obtained successfully`, you're ready.

### 7. Open your dashboard

Visit `https://yourdomain.com` in a browser. You should see the GlycemicGPT login page over HTTPS.

## Updating

To update to the latest GlycemicGPT release:

```bash
docker compose pull
docker compose up -d
```

The `:latest` tag pulls whatever the most recent stable release is.

## Restarting

```bash
docker compose restart
```

## Stopping (keeps data)

```bash
docker compose down
```

Your database, Caddy certificates, and configuration are preserved. Run `docker compose up -d` again to resume.

## Stopping and deleting all data

```bash
docker compose down -v
```

> **The `-v` flag deletes everything**, including your database and certificates. You will start fresh.

## What's exposed?

Only ports 80 and 443. The database, Redis, the API, the web app, and the AI sidecar are all on an internal Docker network and not reachable from outside.

## Troubleshooting

**Caddy keeps trying and failing to get a certificate:**

- Verify your DNS A record is pointing at the right IP: `dig +short yourdomain.com`
- Verify ports 80 and 443 are reachable from the internet (some VPS firewalls block them by default)
- Verify `ACME_EMAIL` in `.env` is a valid email format

**`POSTGRES_PASSWORD is required` error:**

- You haven't filled in `.env` yet. Set the required values and try again.

**Dashboard loads but says "cannot reach API":**

- The API service may still be starting -- check `docker compose ps`
- Look at API logs: `docker compose logs api`

For the full troubleshooting guide, see [GlycemicGPT Troubleshooting](../../../docs/troubleshooting/index.md).

## Alternative deployments

This is one of several ways to deploy GlycemicGPT. Others:

- [`prod-caddy/`](../prod-caddy/) -- minimal Caddy example with manual Caddyfile editing (this one supersedes it for most users)
- [`cloudflare-tunnel/`](../cloudflare-tunnel/) -- run behind Cloudflare with zero exposed ports
- [`external-redis/`](../external-redis/) -- bring your own Redis or Valkey cluster
- [Root `docker-compose.yml`](../../../docker-compose.yml) -- local development on your laptop (no HTTPS)

See the full [Install with Docker](../../../docs/install/docker.md) guide for guidance on choosing.
