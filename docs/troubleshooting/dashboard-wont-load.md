---
title: Dashboard won't load
description: The browser can't reach GlycemicGPT, or the dashboard is blank.
---

You typed the URL and got a browser error, a blank page, a connection timeout, or "this site can't be reached." Here's the order to check things.

## 1. Are the containers running?

From the directory you ran `docker compose up -d` in:

```bash
docker compose ps
```

You should see five GlycemicGPT services (`web`, `api`, `sidecar` or `ai-sidecar` -- that's the AI bridge -- `db`, `redis`) plus a sixth if you're using one of the deploy examples (`caddy` or `cloudflared`). Every service should show `healthy` or `running`.

**If any service shows `exited` or keeps restarting:**

```bash
docker compose logs --tail=100 <service-name>
```

> **What you're looking for in the logs:** scroll to the bottom of what the command prints and look for lines starting with `ERROR`, `FATAL`, or `Exception`. Those are the lines that explain *why* a service stopped. The earlier lines are usually normal startup output. If a problem repeats, you'll see the same error printed every few seconds as the service restarts.

Common causes:
- **`db` exited** -- usually a `POSTGRES_PASSWORD is required` error in the logs. Check `.env` has `POSTGRES_PASSWORD` set.
- **`api` keeps restarting** -- often `SECRET_KEY is required` or a database connection error. Check `.env` and that `db` is healthy.
- **`caddy` or `cloudflared` not healthy** -- they depend on `web` being healthy first. Wait a couple minutes, or check their logs for an explanation.

**If everything is healthy but the dashboard still won't load**, continue to step 2.

## 2. Is the platform reachable from your computer?

Try the API health endpoint directly:

```bash
# Trying it locally
curl http://localhost:8000/health

# Always-on deployment
curl https://yourdomain.com/api/health
```

If you get back `{"status": "healthy", ...}`, the platform is up and the issue is browser-side. Skip to step 4.

If `curl` says "connection refused" or "couldn't resolve host," the platform isn't reachable from the machine you're on. Continue to step 3.

## 3. Networking

### Trying it locally

If you're running the platform on the same computer you're browsing from: you should be able to reach `http://localhost:3000`. If not:

- Verify `docker compose up -d` ran without errors
- Check whether something else is using port 3000: `lsof -i :3000` (macOS / Linux) or `netstat -ano | findstr :3000` (Windows)

If you're running the platform on a different computer (a home server, NAS, or VPS) and trying to reach it from a browser on your laptop:

- Get the platform's IP: `hostname -I` (Linux) or `ipconfig` (Windows) or System Settings → Network (macOS)
- Visit `http://<that-ip>:3000` from your laptop's browser
- If it doesn't load, you may have a firewall blocking inbound connections to port 3000

### Always-on deployment with Cloudflare Tunnel

Visit `https://yoursubdomain.yourdomain.com`.

**If you see Cloudflare error 1033 ("Argo Tunnel error"):**
- Cloudflare can't reach your tunnel. Your home server may be offline, or the cloudflared container isn't running.
- Check: `docker compose logs cloudflared`

**If you see Cloudflare error 502 / 521 ("Web server is down"):**
- The tunnel is connected but the web service isn't responding. Check `docker compose ps` -- if `web` shows unhealthy, look at its logs: `docker compose logs web`

**If you see Cloudflare error 403:**
- Cloudflare's security rules are blocking you. In the Cloudflare dashboard, go to **Security → WAF → Custom rules** and check for rules that might be blocking your IP.

### Always-on deployment with VPS + Caddy

Visit `https://yourdomain.com`.

**If you see "your connection isn't private" / certificate warning:**
- Caddy hasn't finished provisioning the certificate yet. Wait a couple of minutes and reload.
- If it persists, check Caddy logs: `docker compose logs caddy`. Look for errors like:
  - `failed to get certificate: dns: ...` -- your domain's DNS isn't pointing at your server. Run `dig +short yourdomain.com` and verify it returns your server's public IP.
  - `connection refused` to `:80` -- ports 80 and 443 aren't reachable from the internet. Check your VPS firewall (most providers have a firewall in addition to anything you've configured locally).

**If you see "this site can't be reached" / browser timeout:**
- DNS isn't pointing at the server, or ports are blocked. Same checks as above: `dig`, firewall.

## 4. Browser-side issues

The platform is reachable but the page is blank or doesn't render properly:

- **Hard reload** -- shift + click the reload button (or Cmd/Ctrl + Shift + R) to bypass the cache
- **Try a different browser** to rule out a browser extension blocking something
- **Open the developer console** (F12) -- check the Network tab for failed requests and the Console tab for JavaScript errors. If you see `Mixed Content` errors, one of the URLs your dashboard is loading is `http://` while the page itself is loaded over `https://` -- make sure the API URL the frontend uses is `https://` (check `NEXT_PUBLIC_API_URL` or your reverse proxy's upstream config). Mixed Content is unrelated to CORS; CORS errors are handled separately in the next step.

## 5. CORS errors specifically

If the dashboard loads but you see `Access-Control-Allow-Origin` errors in the browser console, your `CORS_ORIGINS` setting is wrong:

```
Access to fetch at 'https://api.yourdomain.com/...' from origin 'https://yourdomain.com' has been blocked by CORS policy
```

Open `.env`, find `CORS_ORIGINS`, and make sure it includes the URL you're visiting from. For an always-on deployment:

```
CORS_ORIGINS=["https://yourdomain.com"]
```

Restart the API after changing it:

```bash
docker compose restart api
```

## Still stuck?

Capture this and bring it to [Discord](https://discord.gg/QbyhCQKDBs) or [GitHub Issues](https://github.com/GlycemicGPT/GlycemicGPT/issues/new/choose).

> **Before posting logs publicly, redact sensitive values.** Logs may contain emails, bearer / API tokens, auth headers, device or account IDs, and pump serial numbers. Replace anything you wouldn't want a stranger to have with `[REDACTED]`, or send the unredacted version via Discord DM to a maintainer instead of posting in a public channel.

```bash
docker compose ps
docker compose logs --tail=50 web
docker compose logs --tail=50 api
```

Also useful: which deployment path you're on (laptop, home server, VPS), and what URL you're trying to load.
