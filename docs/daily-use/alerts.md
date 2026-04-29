---
title: Configuring Alerts
description: Get notified when your glucose crosses a threshold or a pattern breaks.
---

GlycemicGPT can alert you when your glucose crosses thresholds you set, and (if you've linked a caregiver) escalate to them when you don't respond.

> **Alerts are not a substitute for your CGM's own alerts.** Your CGM device's native alerts run on the device itself and don't depend on the platform being up, the network being available, or your phone being charged. Always keep CGM alerts enabled. GlycemicGPT alerts are a supplement, not a replacement.

## What you can set alerts for

In the dashboard, **Settings → Alerts** has thresholds for:

- **Low glucose** -- glucose below your low threshold
- **Urgent low glucose** -- glucose below an urgent-low threshold (typically 55 mg/dL or below)
- **High glucose** -- glucose above your high threshold
- **Sustained high** -- glucose stays above a threshold for a configured duration
- **Stale data** -- no glucose readings for longer than expected (CGM disconnect, sensor issue)
- **Predictive alerts** -- glucose is trending toward a threshold based on the current rate of change *(coming in ROADMAP §Phase 4)*

For each, you can set the threshold value and the cooldown (how long between repeated alerts for the same condition).

## Where alerts are delivered

Multiple channels can be configured under **Settings → Communications**:

| Channel | Best for | Notes |
|---|---|---|
| In-app banner | When you're using the dashboard | Always available |
| Push notifications (Android app) | When you're not actively in the app | Requires the [mobile app](../mobile/install.md) installed and signed in |
| Telegram | If you prefer Telegram for notifications | Requires a Telegram bot configured -- alpha feature today |

You can pick which channels each alert type uses. Some users want urgent lows on every channel, sustained highs only in-app, and so on.

## Caregiver escalation

If you've [linked a caregiver](../caregivers/linking-to-patient.md), alerts can escalate to them when you don't acknowledge an alert within a configured time window. The default escalation flow:

1. Alert fires -- you get notified on your selected channels
2. You either acknowledge it (tap "I'm OK" or similar) or it sits there
3. If you don't acknowledge within the escalation window (configurable, default 15 minutes), the caregiver gets the alert with full context (the threshold that was crossed, the current value, how long it's been low, your recent history)

Escalation is configured per-alert-type. You can choose to skip escalation for less-urgent alerts (sustained high) and only escalate the urgent ones (urgent low).

## Quiet hours

You can set quiet hours in **Settings → Alerts → Quiet hours**. During quiet hours, non-urgent alerts are suppressed. Urgent-low alerts always fire regardless of quiet hours -- you cannot disable urgent-low alerts during quiet hours, by design.

## Acknowledging alerts

When an alert fires, the in-app banner or notification has an **Acknowledge** button. Tapping it:

- Stops the alert from re-firing for the configured cooldown
- Stops the escalation timer (if configured)
- Logs the acknowledgment for the daily brief / patterns

## Why is my alert not firing?

Common causes:

- **Threshold isn't crossing** -- check your dashboard chart. Did the actual glucose value cross the threshold you set?
- **Cooldown active** -- if the same alert fired recently, the cooldown is suppressing repeats
- **Channel not configured** -- check **Settings → Communications**
- **Mobile app not signed in / running** -- push notifications require the app
- **Telegram bot not configured** -- if you set Telegram as a channel but never finished the bot setup

For pattern-based alerts (sustained high, etc.), the alert needs continuous data to evaluate the pattern. If your CGM had a gap during the trigger window, the platform may not fire.

## Why am I getting too many alerts?

Aggressive thresholds or short cooldowns are the usual cause. Tune them in **Settings → Alerts**:

- Increase the threshold (e.g., high alert at 200 mg/dL instead of 180)
- Increase the cooldown (e.g., 30 minutes instead of 10) so the same condition doesn't re-fire constantly
- Move some alerts off your most-distracting channel (e.g., move sustained-high to in-app only, leave urgent-low on push)

## Alerts and your healthcare provider

When you talk with your endocrinologist about your alert thresholds, the platform can include alert history in your printable reports -- they can see when alerts fired and how you responded. This is in **Reports** (the printable PDF you can take to appointments).

## Privacy

- Alert configurations and history are stored on your platform's database
- Push notifications go through your platform's notification service to your phone (no third-party push service in the path)
- Telegram alerts go through Telegram's servers -- if Telegram is in your threat model, don't enable that channel
- Caregiver escalations go through your platform to the caregiver's notification channels (same model as your own alerts)

See [Privacy](../concepts/privacy.md) for the full data flow story.
