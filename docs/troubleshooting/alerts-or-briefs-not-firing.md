---
title: Alerts or briefs aren't firing
description: Configured alerts or daily briefs that don't deliver as expected.
---

You've set up alerts (or daily briefs) and they're not showing up the way you expected. This page walks the typical causes in order. Alerts and briefs share most of the same delivery infrastructure, so the same checks apply to both.

> **GlycemicGPT alerts are a supplement, not a replacement for your CGM's native alerts.** Your CGM device's own alerts run on the device itself and don't depend on this platform being up. Always keep CGM alerts enabled. The checks below are about the platform's *additional* alerts.

## Step 1: Is the alert (or brief) actually configured?

In the dashboard:

- **Alerts** -- **Settings → Alerts**. Make sure the threshold for the alert type you expected is enabled and set to a sensible value.
- **Briefs** -- **Settings → Briefs**. Make sure frequency is set (daily / weekly) and a generation time is selected.

If you're not sure whether an alert *should* have fired, check **Activity → Alerts** for the recent alert history. If the platform fired it but you didn't receive it, the issue is delivery (Step 3 below). If the platform didn't fire it at all, the threshold or condition isn't being met.

## Step 2: Is the AI provider working? (Briefs only)

Briefs are AI-generated. If your AI provider is broken, briefs silently fail in the background.

```bash
docker compose logs --tail=50 sidecar | grep -i brief
```

If you see authentication errors or "no provider configured," fix the AI provider first -- see [AI chat isn't working](./ai-chat-not-working.md). Briefs will start generating again on the next scheduled run.

## Step 3: Is your delivery channel working?

Open **Settings → Communications**. Each channel has a status indicator. Most common issues:

### Push notifications (Android app) aren't arriving

- **The mobile app must be installed and signed in** for push to work. Confirm in the app: open it, you should see your dashboard. If it's signed out, sign in -- push registers on sign-in.
- **Battery optimization is killing the app.** Android aggressively shuts down background apps to save battery -- a known cause of missed alerts. Exempt GlycemicGPT in Settings → Battery → Battery optimization → GlycemicGPT → Don't optimize.
- **Notification permission is off.** On Android 13+, notifications require explicit permission. In phone Settings → Apps → GlycemicGPT → Notifications → make sure it's allowed.
- **Do Not Disturb is active.** Both the OS-level Do Not Disturb and any in-app quiet hours suppress non-urgent alerts. Urgent-low alerts always fire regardless.

To rule the app out: trigger a test alert from **Settings → Alerts → Send test alert**. If the test arrives, the channel works and your real alert configuration is the issue. If the test doesn't arrive, the channel itself is broken.

### Telegram alerts aren't arriving

- **Bot is not configured for your account.** In **Settings → Communications → Telegram**, you should see a "Connected to chat ID: ..." status. If not, the linking step didn't complete.
- **You blocked the bot in Telegram.** Open Telegram, find the bot, and unblock it. Telegram silently drops messages to bots that have been blocked.
- **The platform's bot token expired or was revoked.** Check the API logs: `docker compose logs --tail=50 api | grep -i telegram`. If you see 401 errors, the token in `.env` needs to be refreshed.

### In-app alerts don't show up

- **The dashboard tab needs to be open.** In-app banners are delivered through the open dashboard session. If you closed the tab, push or Telegram are the channels that can still reach you.
- **The browser may be blocking the persistent connection.** Try a different browser to rule it out.

## Step 4: Quiet hours, cooldowns, and escalation windows

A surprising number of "missing alerts" are actually working as configured -- just not the way the user remembered configuring them:

- **Quiet hours** in **Settings → Alerts** suppress non-urgent alerts during the configured window. Urgent-low alerts always fire.
- **Cooldown** between alerts of the same type prevents repeated notifications. If you got an alert 10 minutes ago and the cooldown is 30 minutes, a second condition won't re-fire.
- **Escalation window** delays caregiver delivery. If you set escalation to 15 minutes and acknowledge the alert in 12 minutes, the caregiver never gets it (this is intentional -- so the caregiver isn't pinged for false alarms).

Open **Settings → Alerts** and confirm the values match your expectations.

## Step 5: Brief never appeared

In addition to Step 2 (AI provider), check:

- **Was there enough data?** A morning brief on day 1 of using GlycemicGPT will be empty -- the AI can't summarize what isn't there. Wait a few days.
- **Did the brief generation actually run?** Look at API logs around the configured time: `docker compose logs --tail=100 api | grep -i brief`. You should see a "generating brief" entry near the time you scheduled it.
- **Is the schedule correct?** "Morning" in **Settings → Briefs** is *server time*, not your local time -- if your platform is on a server in a different region, the time will be off.

## Still stuck?

Capture this and bring it to [Discord](https://discord.gg/QbyhCQKDBs):

```bash
docker compose logs --tail=100 api sidecar
```

Plus:
- Which alert / brief you expected
- When you expected it
- What channel you expected to receive it on
- Whether a test alert (Settings → Alerts → Send test alert) arrives
