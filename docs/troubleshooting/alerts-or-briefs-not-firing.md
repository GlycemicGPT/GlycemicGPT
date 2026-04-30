---
title: Alerts or briefs aren't firing
description: Configured alerts or daily briefs that don't deliver as expected.
---

You've set up alerts (or daily briefs) and they're not showing up the way you expected. This page walks the typical causes in order. Alerts and briefs share most of the same delivery infrastructure, so the same checks apply to both.

> **GlycemicGPT alerts are a supplement, not a replacement for your CGM's native alerts.** Your CGM device's own alerts run on the device itself and don't depend on this platform being up. Always keep CGM alerts enabled. The checks below are about the platform's *additional* alerts.

## Step 1: Is the alert (or brief) actually configured?

In the dashboard:

- **Alerts** -- **Settings → Alerts**. Make sure the threshold for the alert type you expected is set to a sensible value. Today's alert types are low / urgent-low / high / urgent-high / IoB warning.
- **Briefs** -- **Settings → Briefs**. Make sure briefs are enabled and a generation time is selected. (Briefs are daily today; weekly is a roadmap item.)

If you're not sure whether an alert *should* have fired, check **Dashboard → Alerts** for the recent alert history. If the platform fired it but you didn't receive it, the issue is delivery (Step 3 below). If the platform didn't fire it at all, the threshold or condition isn't being met.

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
- **Do Not Disturb is active.** OS-level Do Not Disturb on your phone suppresses notifications. Check that GlycemicGPT is in any "allowed during DND" exception list, or temporarily disable DND when troubleshooting.

> Note: there's no built-in "send test alert" button today. If you need to verify your channel is working end-to-end, the practical test is temporarily lowering your high-warning threshold below your current glucose value, waiting for the next polling cycle, and seeing if the alert arrives. Restore your real threshold afterward.

### Telegram alerts aren't arriving

- **Bot is not configured for your account.** In **Settings → Communications → Telegram**, you should see a "Connected to chat ID: ..." status. If not, the linking step didn't complete.
- **You blocked the bot in Telegram.** Open Telegram, find the bot, and unblock it. Telegram silently drops messages to bots that have been blocked.
- **The platform's bot token expired or was revoked.** Check the API logs: `docker compose logs --tail=50 api | grep -i telegram`. If you see 401 errors, the token in `.env` needs to be refreshed.

### In-app alerts don't show up

- **The dashboard tab needs to be open.** In-app banners are delivered through the open dashboard session. If you closed the tab, push or Telegram are the channels that can still reach you.
- **The browser may be blocking the persistent connection.** Try a different browser to rule it out.

## Step 4: Deduplication window and escalation timing

A surprising number of "missing alerts" are actually working as configured -- just not the way the user remembered configuring them:

- **Deduplication window** -- the platform suppresses repeats of the same alert type within a 30-minute window. If you got an alert 10 minutes ago and the same condition is still active, a second one won't fire. (This window is currently global, not configurable per alert type.)
- **Escalation timing** -- caregiver delivery is delayed by the configured tier delays. Defaults: reminder at 5 min, primary contact at 10 min, all contacts at 20 min after the original alert. If you acknowledge before the relevant tier fires, the caregiver never gets pinged (this is intentional -- so the caregiver isn't pinged for false alarms). Configure under **Settings → Alerts**.

Note: quiet-hours / time-window suppression is **not implemented today** -- if you set a high-warning to 180 mg/dL it will fire whenever you're above 180, regardless of time of day. Quiet hours are on the roadmap.

## Step 5: Brief never appeared

In addition to Step 2 (AI provider), check:

- **Was there enough data?** A morning brief on day 1 of using GlycemicGPT will be empty -- the AI can't summarize what isn't there. Wait a few days.
- **Did the brief generation actually run?** Look at API logs around the configured time: `docker compose logs --tail=100 api | grep -i brief`. You should see a "generating brief" entry near the time you scheduled it.
- **Is the schedule correct?** "Morning" in **Settings → Briefs** is *server time*, not your local time -- if your platform is on a server in a different region, the time will be off.

## Still stuck?

Capture this and bring it to [Discord](https://discord.gg/QbyhCQKDBs).

> **Before posting logs publicly, redact sensitive values.** Logs may contain emails, bearer / API tokens, auth headers, device or account IDs, and Telegram bot tokens. Replace anything you wouldn't want a stranger to have with `[REDACTED]`, or send the unredacted version via Discord DM to a maintainer instead of posting in a public channel.

```bash
docker compose logs --tail=100 api sidecar
```

Plus:
- Which alert / brief you expected
- When you expected it
- What channel you expected to receive it on
- The result of the temporary-threshold test described in Step 3 (did the manually-triggered alert arrive)
