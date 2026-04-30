---
title: Troubleshooting
description: Find what you're seeing and follow the path to fix it.
---

Something not working? Find the symptom you're seeing below.

| What you're seeing | Most likely cause | Where to go |
|---|---|---|
| Dashboard won't open at all (browser timeout, blank page, "can't reach this site") | Platform isn't running, or you're on the wrong URL | [Dashboard won't load](./dashboard-wont-load.md) |
| Dashboard loads but glucose isn't updating | Phone app not connected to pump, or sync stopped | [BG isn't updating](./bg-not-updating.md) |
| Mobile app can't pair with your pump | Bluetooth permissions, pump already paired with another app, pump out of range | [Can't pair pump](./cant-pair-pump.md) |
| AI chat is stuck loading or shows errors | AI provider not configured or token expired | [AI chat isn't working](./ai-chat-not-working.md) |
| AI chat answers but the answer is wrong, weird, or made up | Smaller / cheaper AI model, or the AI doesn't have enough context | [AI chat isn't working -- wrong answers](./ai-chat-not-working.md#step-6-ai-chat-returns-wrong--weird-answers) |
| Alerts aren't firing when they should | Notification channel not configured, OS-level battery optimization killing the app, or threshold settings off | [Alerts or briefs aren't firing](./alerts-or-briefs-not-firing.md) |
| Daily brief never showed up | Brief schedule misconfigured, AI provider failing in the background, or notification channel issue | [Alerts or briefs aren't firing](./alerts-or-briefs-not-firing.md) |

If your situation isn't covered above, the [community Discord](https://discord.gg/QbyhCQKDBs) is the fastest place to ask. For a formal bug report, [file an issue on GitHub](https://github.com/GlycemicGPT/GlycemicGPT/issues/new/choose).

## Common starting checks

Before diving into a specific page, two checks resolve a surprising number of issues:

### Check the platform is actually running

```bash
docker compose ps
```

Every service should show `healthy` or `running`. If anything shows `unhealthy`, `exited`, or `restarting`, that's the problem -- look at its logs:

```bash
docker compose logs <service-name>
```

Replace `<service-name>` with `web`, `api`, `sidecar` (the AI bridge), `db`, `redis`, or (if you're using one of the deploy examples) `caddy` or `cloudflared`.

### Check the platform's health endpoint

```bash
curl http://localhost:8000/health
```

Or for an always-on deployment:

```bash
curl https://yourdomain.com/api/health
```

If this returns `{"status": "healthy", "database": "connected"}`, the platform's core is working and the issue is somewhere else (likely the mobile app, AI provider config, or a specific feature). If it doesn't return at all, the platform itself isn't reachable -- start with [Dashboard won't load](./dashboard-wont-load.md).

## A few honest reminders before you dig in

- **GlycemicGPT is alpha software.** Some failure modes are because the project is still maturing, not because you did something wrong. If you can reproduce the problem cleanly, [file an issue](https://github.com/GlycemicGPT/GlycemicGPT/issues/new/choose) -- that's how things get fixed.
- **Not every issue here is a software problem.** Bluetooth, Wi-Fi, DNS, and battery-saver settings on your phone can cause symptoms that look like GlycemicGPT bugs.
- **GlycemicGPT does not give medical advice.** If a glucose reading on the dashboard looks wrong (a value that doesn't match what you see on your CGM directly), do not assume the dashboard is right. Verify against your CGM's official app and consult your healthcare provider for any medical decisions.

## Still stuck?

Two channels for help, depending on what you need:

| You want... | Use this |
|---|---|
| Real-time chat, hands-on help, "is this normal?" questions | [Discord](https://discord.gg/QbyhCQKDBs) |
| A formal bug report (something is genuinely broken and reproducible) | [GitHub Issues](https://github.com/GlycemicGPT/GlycemicGPT/issues/new/choose) |

When asking for help, the most useful information is:

- Which deployment path you're on (laptop, home server with Cloudflare Tunnel, VPS with Caddy)
- What `docker compose ps` shows
- The most recent ~50 lines of logs from the failing service: `docker compose logs --tail=50 <service-name>`
- Your platform version (look in **Settings → About** in the dashboard, or `docker images | grep glycemicgpt`)

> **Before posting logs publicly, redact sensitive values.** Logs may contain emails, bearer / API tokens, auth headers, device or account IDs, pump serial numbers, AI-provider tokens, and Telegram bot tokens. Replace anything you wouldn't want a stranger to have with `[REDACTED]`, or send the unredacted version via Discord DM to a maintainer instead of posting in a public channel.
