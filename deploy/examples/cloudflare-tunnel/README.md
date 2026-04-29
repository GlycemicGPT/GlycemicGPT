# Public access via Cloudflare Tunnel

This is a setup for running GlycemicGPT and exposing it publicly without opening any inbound ports on your server. It works equally well for:

- **A computer at home** -- desktop, NAS, mini-PC, Raspberry Pi, or any machine running 24/7
- **A cloud VPS** -- if you'd rather not expose any ports on your VPS to the internet

**You do not need:**

- A public static IP from your ISP (relevant for home setups)
- Port forwarding configured on your router (home setups)
- Inbound firewall rules on your VPS (cloud setups)
- A reverse proxy you maintain
- TLS certificates you renew manually

**Cloudflare handles all of that.** Your server (wherever it is) makes one outbound connection to Cloudflare; Cloudflare proxies inbound traffic from your domain to your server through that connection. No inbound ports open at all.

## Why this might be more secure than opening ports

The standard "VPS + Caddy + Let's Encrypt" pattern requires inbound ports 80 and 443 to be open to the entire internet. Even with Caddy in front, you've put TLS termination, HTTP parsing, and your application surface directly on the public internet -- which means:

- Every script kiddie scanning the internet can probe your server
- Any 0-day in your reverse proxy or web stack is reachable from anywhere
- Your VPS provider's firewall is the only thing between you and the world's traffic

With Cloudflare Tunnel, your server has **zero inbound ports open**. Cloudflare is in front of you doing TLS termination, DDoS protection, and (with Cloudflare Access if you set it up) authentication at the edge -- requests only reach your server through the tunnel after Cloudflare has already decided to forward them. For a small open-source project running on hardware you can't 24/7 monitor, that's a meaningful security improvement.

The tradeoff: Cloudflare is in your data path. They see encrypted HTTPS traffic. Per their terms they don't inspect Tunnel traffic for normal use, but if Cloudflare-as-a-third-party is in your threat model, the [`public-cloud/`](../public-cloud/) example (Caddy + Let's Encrypt + your VPS firewall, no Cloudflare in the path) is the alternative.

This setup is free for the volume of traffic GlycemicGPT generates -- it sits comfortably within Cloudflare's free tier.

## What you'll need

- A computer or VPS running 24/7 with Docker and Docker Compose installed (for home: a desktop, NAS, mini-PC, Raspberry Pi; for cloud: any small VPS will do)
- A [Cloudflare](https://www.cloudflare.com) account (free)
- A domain name added to Cloudflare. You can:
  - Buy a new one through Cloudflare ($8-15/year typical)
  - Transfer an existing domain to Cloudflare
  - Or just point an existing domain's nameservers at Cloudflare

If you don't have a domain yet, the simplest option is buying one through Cloudflare directly -- it skips the nameserver step.

## Steps

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

1. Click **Networks** → **Tunnels** → **Create a tunnel**
2. Choose **Cloudflared** as the connector type
3. Give the tunnel a name (e.g., `glycemicgpt-home`)
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

On your home server, in the `deploy/examples/cloudflare-tunnel/` directory:

```bash
cp .env.example .env
```

Open `.env` in your editor and fill in:

| Variable | What to put |
|---|---|
| `CLOUDFLARE_TUNNEL_TOKEN` | The token you copied in step 3 |
| `POSTGRES_PASSWORD` | Run `openssl rand -hex 32`, paste output |
| `REDIS_PASSWORD` | Run `openssl rand -hex 32`, paste output |
| `SECRET_KEY` | Run `openssl rand -hex 32`, paste output |
| `CORS_ORIGINS` | `["https://glycemicgpt.yourdomain.com"]` (the public hostname you set in step 4) |

### 6. Start everything

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

Look for a line like `Connection registered`. When you see that, your tunnel is live.

### 8. Open your dashboard

Visit `https://glycemicgpt.yourdomain.com` (the public hostname from step 4). You should see the GlycemicGPT login page over HTTPS, served through Cloudflare.

The first request might take a couple seconds while Cloudflare establishes the connection. Subsequent requests are fast.

## Updating

```bash
docker compose pull
docker compose up -d
```

The `:latest` tag pulls the most recent stable release.

## Stopping (keeps data)

```bash
docker compose down
```

Your database, configuration, and tunnel token are preserved.

## Stopping and deleting all data

```bash
docker compose down -v
```

> **The `-v` flag deletes everything**, including your database. You will start fresh.

## What's exposed?

**Nothing.** No inbound ports are open on your home network or router. Your home server makes a single outbound HTTPS connection to Cloudflare; all inbound traffic comes through that connection.

Your ISP cannot see what's flowing through the tunnel. Cloudflare can technically see the encrypted traffic but does not inspect it for normal Tunnel use. If your threat model excludes Cloudflare entirely, the [`public-cloud` example](../public-cloud/) (Caddy + Let's Encrypt on a VPS you control) is the alternative.

## Mobile app configuration

When you set up the GlycemicGPT mobile app, point it at your Cloudflare hostname:

```
https://glycemicgpt.yourdomain.com
```

The mobile app uses the same domain regardless of whether you're at home or away -- Cloudflare routes the request to your home server either way.

## Troubleshooting

**Tunnel doesn't start / connector unhealthy:**
- Verify `CLOUDFLARE_TUNNEL_TOKEN` is set correctly in `.env` (it's a long string starting with `eyJ...`)
- Check the cloudflared logs: `docker compose logs cloudflared`
- Make sure your home server has outbound internet access on port 443

**Domain shows Cloudflare error 1033 ("Argo Tunnel error"):**
- Means Cloudflare cannot reach your tunnel. Check your home server is online and the cloudflared container is running.

**Domain shows error 502 / 521 ("Web server is down"):**
- Tunnel is connected but the web service isn't responding. Check `docker compose ps` -- if `web` shows as unhealthy, look at its logs: `docker compose logs web`

**Mobile app can't connect:**
- Verify `CORS_ORIGINS` in `.env` includes your full Cloudflare URL with `https://`
- Restart the API service after changing CORS: `docker compose restart api`

For the full troubleshooting guide, see [GlycemicGPT Troubleshooting](../../../docs/troubleshooting/index.md).

## When to use this vs. other options

- **You're using this** -- you have a computer at home running 24/7, you want public access, you want the simplest setup
- **Use [`public-cloud/`](../public-cloud/) instead** -- you don't have a home server (or don't want to run one). Renting a VPS is simpler than maintaining hardware.
- **Use [`prod-caddy/`](../prod-caddy/) instead** -- you have a home server with a public IP and want to handle TLS yourself without involving Cloudflare
- **Use the [root `docker-compose.yml`](../../../docker-compose.yml)** -- you only need access on your home network, no public exposure required
