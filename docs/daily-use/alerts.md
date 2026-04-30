---
title: Configuring Alerts
description: Get notified when your glucose crosses a threshold, with optional caregiver escalation.
---

GlycemicGPT can alert you when your glucose crosses thresholds you set, and (if you've linked a caregiver) escalate to them when you don't respond.

> **Alerts are not a substitute for your CGM's own alerts.** Your CGM device's native alerts run on the device itself and don't depend on the platform being up, the network being available, or your phone being charged. Always keep CGM alerts enabled. GlycemicGPT alerts are a supplement, not a replacement.

## Alert types today

In the dashboard, **Settings → Alerts** has thresholds for:

- **Low glucose** (warning) -- glucose at or below your low threshold (default 70 mg/dL)
- **Urgent low glucose** -- glucose at or below your urgent-low threshold (default 55 mg/dL)
- **High glucose** (warning) -- glucose at or above your high threshold (default 180 mg/dL)
- **Urgent high glucose** -- glucose at or above your urgent-high threshold (default 250 mg/dL)
- **IoB warning** -- insulin-on-board exceeds a configurable safety threshold

You can set the threshold value for each. Alert types not yet shipped (and how to track them):

- **Sustained-high alerts** (e.g., "above target for 90 minutes") -- on the roadmap, not in today's alert types
- **Stale-data alerts** ("no readings for 30 minutes") -- on the roadmap, not in today's alert types
- **Predictive alerts** (trajectory-based "you'll be low in 15 minutes") -- on the roadmap, see [ROADMAP.md](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/ROADMAP.md) §Phase 4
- **Per-alert-type cooldown configuration** -- the platform applies a global 30-minute deduplication window between repeats of the same alert type today; making this configurable per type is a future enhancement
- **Quiet hours / time-window suppression** -- not implemented today; on the roadmap

## Where alerts are delivered

Multiple channels can be configured under **Settings → Communications**:

| Channel | Best for | Notes |
|---|---|---|
| In-app banner | When you're using the dashboard | Always available; delivered via Server-Sent Events to the open dashboard |
| Push notifications (Android app) | When you're not actively in the app | Requires the [mobile app](../mobile/install.md) installed and signed in |
| Telegram | If you prefer Telegram for notifications | Requires a Telegram bot configured -- alpha feature today |

You can pick which channels each alert type uses. Some users want urgent lows on every channel, less-urgent alerts only in-app, and so on.

## Caregiver escalation

If you've [linked a caregiver](../caregivers/linking-to-patient.md), alerts can escalate to them when you don't acknowledge an alert within a configured time window. The escalation flow has three tiers:

1. **Reminder** (default 5 minutes after the alert fires) -- the platform reminds *you* to acknowledge
2. **Primary contact** (default 10 minutes) -- if you still haven't acknowledged, your designated primary caregiver gets notified
3. **All contacts** (default 20 minutes) -- if still no acknowledgment, all linked caregivers with escalation permission get notified

Each tier's delay is configurable per user (Settings → Alerts → Escalation timing). Escalation is configured per-alert-type -- you can disable escalation for the less-urgent types and keep it on for urgent-low.

The escalation message itself is intentionally brief -- patient identifier, what triggered the alert, current glucose, severity. See [Receiving alerts as a caregiver](../caregivers/receiving-alerts.md) for the caregiver side.

## Acknowledging alerts

When an alert fires, the in-app banner or notification has an **Acknowledge** button. Tapping it:

- Stops the escalation timer (so caregivers don't get pinged)
- Logs the acknowledgment for the daily brief / patterns
- Marks the alert as resolved in your alert history

You can see the recent alert history at **Dashboard → Alerts**.

## Why is my alert not firing?

Common causes:

- **Threshold isn't crossing** -- check your dashboard chart. Did the actual glucose value cross the threshold you set?
- **Deduplication window** -- if the same alert type fired in the last 30 minutes, the platform suppresses the repeat
- **Channel not configured** -- check **Settings → Communications**
- **Mobile app not signed in / running** -- push notifications require the app
- **Telegram bot not configured** -- if you set Telegram as a channel but never finished the bot setup

See [Alerts or briefs aren't firing](../troubleshooting/alerts-or-briefs-not-firing.md) for the full troubleshooting walkthrough.

## Why am I getting too many alerts?

Aggressive thresholds are the usual cause. Tune them in **Settings → Alerts**:

- Raise the high-warning threshold (e.g., 200 mg/dL instead of 180) so it fires less often
- Move some alert types off your most-distracting channel (e.g., move high-warning to in-app only, leave urgent-low on push)
- Adjust caregiver escalation timing so you have more breathing room before a caregiver gets pinged

## Alerts and your healthcare provider

When you talk with your endocrinologist about your alert thresholds, the platform can include alert history in your printable reports -- they can see when alerts fired and how you responded. Reports are accessible today from **Settings → Data → Reports**.

## Privacy

- Alert configurations and history are stored on your platform's database
- Push notifications go through your platform's notification service to your phone (no third-party push service in the path)
- Telegram alerts go through Telegram's servers -- if Telegram is in your threat model, don't enable that channel
- Caregiver escalations go through your platform to the caregiver's notification channels (same model as your own alerts)

See [Privacy](../concepts/privacy.md) for the full data flow story.
