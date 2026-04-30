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
| Deploy on a rented cloud server (VPS) with a public domain | [`deploy/examples/public-cloud/`](https://github.com/GlycemicGPT/GlycemicGPT/tree/main/deploy/examples/public-cloud) | Caddy with Let's Encrypt (automatic) | **Recommended for cloud deployments.** Single `.env` file to fill in, automatic HTTPS, sane security defaults. |
| Run on a home computer or VPS with no inbound ports open | [`deploy/examples/cloudflare-tunnel/`](https://github.com/GlycemicGPT/GlycemicGPT/tree/main/deploy/examples/cloudflare-tunnel) | Cloudflare-managed | Most secure path for home users. Requires a free Cloudflare account. |

Advanced scenarios -- skip these unless you specifically need them:

- **Use your own Redis or Valkey cluster** -- [`deploy/examples/external-redis/`](https://github.com/GlycemicGPT/GlycemicGPT/tree/main/deploy/examples/external-redis). For users with existing infrastructure.
- **Use pre-built images and bring your own reverse proxy** (nginx, Traefik, etc.) -- [`docker-compose.prod.yml`](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/docker-compose.prod.yml).

## The five services

Whichever setup you use, GlycemicGPT runs five services:

- **`web`** -- The dashboard you visit in your browser. Serves on port 3000 locally, or proxied through HTTPS on an always-on deployment.
- **`api`** -- The backend that handles your data, settings, and account. Serves on port 8000 locally, or proxied internally on an always-on deployment.
- **`sidecar`** -- The AI bridge. When you chat with the AI, your message goes here, then to your AI provider, then back to you. Internal-only.
- **`db`** -- A PostgreSQL database. This is where your data is stored. Internal-only.
- **`redis`** -- A short-term memory store the platform uses to keep your sign-in session active and to deliver real-time dashboard updates quickly. Internal-only.

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

#### What happens during an upgrade

When the API container starts, it automatically runs any pending database schema migrations (we use Alembic). For most upgrades you don't need to do anything beyond the two commands above. A few things to be aware of:

- **Take a backup before major upgrades.** See [Backups](#backups) below. If a migration fails partway through, the easiest recovery is restoring the dump.
- **Migrations that fail will keep the API container in a restart loop** -- you'll see the same migration error repeating in `docker compose logs api`. Read the error, fix it (usually a manual SQL fix), and the container will succeed on the next restart.
- **Released breaking-change migrations are called out in the release notes** on the GitHub Releases page. For non-breaking releases the upgrade is push-button; for breaking ones, read the notes first.

If the schema change between versions is too disruptive, the safest path is: take a `pg_dump`, `docker compose down -v` (which drops the volume), `docker compose up -d` on the new version (which creates a fresh schema), then restore your dump selectively. This is rarely needed -- documenting it for completeness.

### Backups

GlycemicGPT does not ship an automated backup service in the default Docker setup. (The Kubernetes deployment does -- a daily `pg_dump` CronJob to a PVC; see [Install with Kubernetes](./kubernetes.md).) For Docker users, you take backups manually or via a host-side cron job.

#### Manual backup

```bash
docker compose exec db pg_dump -U glycemicgpt glycemicgpt > glycemicgpt-backup-$(date +%Y%m%d).sql
```

That gives you a complete SQL dump of every table -- glucose, pump events, AI chat history, accounts, settings. Move the file off the host (S3, another machine, an external drive) so a host failure doesn't lose your only backup.

#### Restore from a backup

```bash
# Stop the API and web services so nothing writes while we restore
docker compose stop api web sidecar

# Pipe the dump back in
cat glycemicgpt-backup-20260429.sql | docker compose exec -T db psql -U glycemicgpt glycemicgpt

# Restart
docker compose start api web sidecar
```

#### Recurring backup via host cron

A typical setup: a host-side cron line that runs `pg_dump` daily and rotates the last 14 days. Example for `crontab -e`:

```cron
0 3 * * * cd /home/you/glycemicgpt && docker compose exec -T db pg_dump -U glycemicgpt glycemicgpt | gzip > backups/glycemicgpt-$(date +\%Y\%m\%d).sql.gz && find backups/ -name "glycemicgpt-*.sql.gz" -mtime +14 -delete
```

Adjust the path. Make sure `backups/` exists. Test the restore at least once before relying on it -- backups that have never been restored are not real backups.

#### Backups vs exports

This is *backup* -- a SQL dump suitable for restoring to another GlycemicGPT instance. If you want exports in CSV or other portable formats for use outside GlycemicGPT, see [Exporting your data](../daily-use/data-export.md).

## Deploying for public access

Two paths, depending on what you want:

| If you want... | Use this path |
|---|---|
| Public access without opening any inbound ports on your server (home or VPS) | [Cloudflare Tunnel](#deploying-with-cloudflare-tunnel-home-server-or-vps) |
| Public access on a VPS with your own reverse proxy and Let's Encrypt HTTPS | [VPS with Caddy + Let's Encrypt](#deploying-to-a-vps-with-https) |

Both give you a public URL the mobile app can reach from anywhere. The Cloudflare Tunnel path works equally well on a computer at home and on a cloud VPS, and is often the simpler and more secure option. The Caddy + Let's Encrypt path is what you want if you specifically don't want Cloudflare in your data path -- you handle TLS yourself with Let's Encrypt directly.

## Deploying with Cloudflare Tunnel (home server or VPS)

Run GlycemicGPT and reach it publicly through a Cloudflare-managed tunnel. **You do not need a public IP from your ISP, port forwarding on your router, or TLS certificates to renew.** Your server makes one outbound connection to Cloudflare; all inbound traffic comes through that.

This works equally well for:

- A computer at home (desktop, NAS, mini-PC, Raspberry Pi -- anything running 24/7)
- A cloud VPS where you don't want to expose any inbound ports

### Why this is often more secure than opening ports

The standard "VPS + reverse proxy + Let's Encrypt" pattern requires inbound ports 80 and 443 to be open to the entire internet. Even with a reverse proxy in front, you've put TLS termination, HTTP parsing, and your application surface directly on the public internet -- which means:

- Every script kiddie scanning the internet can probe your server
- Any 0-day in your reverse proxy or web stack is reachable from anywhere
- Your VPS provider's firewall is the only thing between you and the world's traffic

With Cloudflare Tunnel, your server has **zero inbound ports open**. Cloudflare is in front of you doing TLS termination, DDoS protection, and (with Cloudflare Access if you set it up) authentication at the edge -- requests only reach your server through the tunnel after Cloudflare has already decided to forward them.

The tradeoff: Cloudflare is in your data path. They see encrypted HTTPS traffic. Per their terms they don't inspect Tunnel traffic for normal use, but if Cloudflare-as-a-third-party is in your threat model, the [VPS + Caddy](#deploying-to-a-vps-with-https) path keeps Cloudflare out of the picture.

### What you'll need

- A computer or VPS running 24/7 with Docker and Docker Compose installed
- Docker installed (see [Installing Docker](#installing-docker) above if you don't have it)
- A [Cloudflare](https://www.cloudflare.com) account (free)
- A domain name added to Cloudflare. You can:
  - Buy a new one through Cloudflare ($8-15/year typical)
  - Transfer an existing domain to Cloudflare
  - Or just point an existing domain's nameservers at Cloudflare

If you don't have a domain yet, the simplest option is buying one through Cloudflare directly -- it skips the nameserver step.

### 1. Add your domain to Cloudflare

If your domain is already on Cloudflare (you see it at [dash.cloudflare.com](https://dash.cloudflare.com)), skip to step 2.

If not:

- Sign in to [dash.cloudflare.com](https://dash.cloudflare.com)
- Click **Add a site** and follow the wizard
- Cloudflare will give you two nameservers (e.g., `coraline.ns.cloudflare.com`)
- Update your domain registrar to use those nameservers
- Wait 5 minutes to a few hours for the change to propagate

When the domain shows as **Active** in Cloudflare, you're ready.

### 2. Sign in to Cloudflare Zero Trust

Cloudflare Tunnel lives in the Zero Trust dashboard at [one.dash.cloudflare.com](https://one.dash.cloudflare.com).

The first time you visit, you'll be prompted to:

- Pick a team name (any short identifier, like your last name or your home network name -- this is just for your account)
- Choose a free plan (it's actually free, no credit card required)

### 3. Create a tunnel

In the Zero Trust dashboard:

1. Click **Networks → Tunnels → Create a tunnel**
2. Choose **Cloudflared** as the connector type
3. Give the tunnel a name (e.g., `glycemicgpt-home` or `glycemicgpt-vps`)
4. Cloudflare will show you a **token** -- this is a long string starting with `eyJ...`. Copy it. You'll paste it into `.env` in step 5.
5. Skip the install instructions Cloudflare shows (we'll run cloudflared in Docker, not directly on the host)
6. Click **Next** to get to the routing config

### 4. Configure tunnel routing

You're now on the **Public Hostnames** tab.

Click **Add a public hostname** and fill in:

| Field | Value |
|---|---|
| Subdomain | `glycemicgpt` (or whatever you want -- this becomes part of your URL) |
| Domain | Your domain on Cloudflare |
| Type | `HTTP` |
| URL | `web:3000` |

`web:3000` is the GlycemicGPT web service inside the Docker network. The cloudflared container runs in the same Docker Compose stack and can reach it by service name.

Click **Save tunnel**.

> If you want both the dashboard AND direct API access (e.g., for the mobile app to skip the web proxy), add a second public hostname pointing at `api:8000` -- e.g., subdomain `api` for the API. For most users, one hostname pointing at `web:3000` is enough; the web service proxies API requests internally.

### 5. Configure `.env`

On your server, in a terminal in the `GlycemicGPT` folder you cloned, navigate into the cloudflare-tunnel example:

```bash
cd deploy/examples/cloudflare-tunnel/
cp .env.example .env
```

Open `.env` in your editor and fill in:

| Variable | What to put |
|---|---|
| `CLOUDFLARE_TUNNEL_TOKEN` | The token you copied in step 3 |
| `POSTGRES_PASSWORD` | Run `openssl rand -hex 32` in a terminal, paste output |
| `REDIS_PASSWORD` | Run `openssl rand -hex 32`, paste output |
| `SECRET_KEY` | Run `openssl rand -hex 32`, paste output |
| `CORS_ORIGINS` | `["https://glycemicgpt.yourdomain.com"]` (the public hostname you set in step 4) |

### 6. Start everything

Still in the `deploy/examples/cloudflare-tunnel/` directory:

```bash
docker compose up -d
```

This pulls the prebuilt GlycemicGPT images, starts all five GlycemicGPT services plus the cloudflared connector. The tunnel registers itself with Cloudflare automatically once it starts.

### 7. Verify

```bash
docker compose ps
```

You should see all six services healthy. Watch the cloudflared logs to confirm the tunnel is connected:

```bash
docker compose logs -f cloudflared
```

Look for a line like `Connection registered`. When you see that, your tunnel is live. Press `Ctrl+C` to stop watching the logs (the services keep running).

### 8. Open your dashboard

Visit `https://glycemicgpt.yourdomain.com` (the public hostname from step 4). You should see the GlycemicGPT login page over HTTPS, served through Cloudflare.

The first request might take a couple seconds while Cloudflare establishes the connection. Subsequent requests are fast.

### Mobile app configuration

When you set up the GlycemicGPT mobile app, point it at your Cloudflare hostname:

```
https://glycemicgpt.yourdomain.com
```

The mobile app uses the same domain regardless of whether you're at home or away -- Cloudflare routes the request to your server either way.

### What's exposed?

Nothing. No inbound ports are open on your server. Your server makes a single outbound HTTPS connection to Cloudflare; inbound traffic for your domain comes through that connection.

### Cloudflare Tunnel troubleshooting

**Tunnel doesn't start / connector unhealthy:**

- Verify `CLOUDFLARE_TUNNEL_TOKEN` is set correctly in `.env` (a long string starting with `eyJ...`)
- Check the cloudflared logs: `docker compose logs cloudflared`
- Make sure your server has outbound internet access on port 443

**Domain shows Cloudflare error 1033 ("Argo Tunnel error"):**

- Cloudflare can't reach your tunnel. Your server may be offline, or the cloudflared container isn't running.

**Domain shows error 502 / 521 ("Web server is down"):**

- Tunnel is connected but the web service isn't responding. Check `docker compose ps` -- if `web` shows as unhealthy, look at its logs: `docker compose logs web`

**Mobile app can't connect:**

- Verify `CORS_ORIGINS` in `.env` includes your full Cloudflare URL with `https://`
- Restart the API service after changing CORS: `docker compose restart api`

## Deploying to a VPS with HTTPS

The path for users who don't run hardware at home (or prefer not to). You rent a small cloud server, point a domain at it, and Caddy provisions HTTPS automatically via Let's Encrypt.

### What you'll need

- A VPS or cloud server (Hetzner, DigitalOcean, Linode, OVH, AWS Lightsail -- any provider works)
- Docker installed on the server (see [Installing Docker](#installing-docker) above)
- A domain name and DNS access to point it at your server

### 1. Set up DNS

In your domain registrar's DNS settings, add an `A` record:

```
glycemicgpt.example.com    A    <your server's public IP>
```

DNS propagation usually takes a few seconds to an hour. Check it's working (using the same hostname you put in the A record):

```bash
dig +short glycemicgpt.example.com
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

## Connecting devices

Once you're signed in, you can connect your devices in the dashboard's settings:

- **Dexcom G7** -- Cloud API. You'll provide your Dexcom Share account credentials.
- **Tandem t:slim X2** -- Two paths:
  - **Cloud (t:connect)** -- You'll provide your Tandem account credentials. The cloud syncs every ~60 minutes.
  - **BLE direct** -- Real-time data via Bluetooth. Requires the [GlycemicGPT mobile app](../mobile/install.md).

Detailed device-connection walkthroughs are in [Daily Use](../daily-use/connecting-dexcom.md).

## When to use Kubernetes instead

Docker Compose is the right choice for most users. Use Kubernetes only if you already run a homelab or production Kubernetes cluster and prefer to deploy GlycemicGPT alongside your other workloads. See [Install with Kubernetes](./kubernetes.md).

A one-click managed deploy (Railway, Fly.io) is on the roadmap -- see [ROADMAP.md](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/ROADMAP.md) §Phase 4.

## Troubleshooting

If something isn't working, see [Troubleshooting](../troubleshooting/index.md). The most common starting points:

- Dashboard won't load → check `docker compose ps` for unhealthy services
- Glucose isn't updating → check device connection in dashboard settings
- AI chat isn't responding → check the sidecar service is running and your AI provider is configured
- Caddy can't get a certificate → DNS not pointing at the server, or ports 80/443 blocked
