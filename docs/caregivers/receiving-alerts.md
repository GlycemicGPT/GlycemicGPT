---
title: Receiving Alerts as a Caregiver
description: How escalated alerts reach you and what to do with them.
---

When you're linked as a caregiver to a patient with alert-escalation permission, you receive alerts when the patient doesn't respond to a critical condition in time. This page covers what that flow looks like and how to set it up on your end.

## How escalation works

The escalation flow:

1. **A patient's glucose crosses an alert threshold** -- e.g., urgent low (below 55 mg/dL)
2. The platform notifies the patient through their configured channels (in-app, push notification, etc.)
3. The patient has a configurable window (default 15 minutes) to acknowledge the alert
4. If they don't acknowledge it, the alert **escalates to you** -- you get a notification on your configured channels
5. The notification includes context: the threshold that was crossed, the current glucose value, how long it's been low, and recent history
6. You can call/text/check on the patient as appropriate

**Acknowledging an alert is the patient's action, not yours.** When you get an escalated alert and you reach the patient, the patient acknowledges it from their end. This is intentional -- the system tracks "did the patient respond" as a real signal, separate from "did the caregiver react."

## What channels alerts can reach you on

Configurable in **Settings → Communications** (in the caregiver's account):

- **In-app banner** -- when you're using the GlycemicGPT dashboard (limited use unless you're constantly on the platform)
- **Push notifications** -- via the GlycemicGPT mobile app on your own phone (you install the [Android app](../mobile/install.md) on your phone too, just like the patient does)
- **Telegram** -- if the patient's platform has a Telegram bot configured

For most caregivers, push notifications via the mobile app are the primary channel. Telegram is the alpha alternative.

## Setting up the mobile app on your phone

Same install process as a patient -- see [Install the Android App](../mobile/install.md). Differences:

- You sign in with your caregiver account, not the patient's account
- The app shows a patient picker if you're caregiver for multiple patients
- The home screen shows the patient's data (read-only) -- you cannot pair a pump or change patient settings from the caregiver app
- Push notifications use the platform's notification service (no third-party in the path)

## What's in an escalated alert

When you receive an escalated alert, it includes:

- **Patient name / label**
- **What triggered the alert** -- e.g., "Urgent low: glucose 50 mg/dL"
- **How long this condition has been active** -- e.g., "Below 55 for 18 minutes"
- **Recent context** -- glucose trend, last bolus / meal, recent activity
- **Time since the patient last interacted with the app** -- can help judge whether they're asleep, busy, or potentially incapacitated

## What you should do

This is not medical advice -- the appropriate response depends on the patient, the alert type, and your relationship. General patterns:

- **Urgent low**: call or text the patient. If they don't respond and you're nearby, check on them. If they're not answering and you're concerned, the standard hypoglycemia response (glucagon, emergency services) is your call to make based on their care plan.
- **Sustained high**: less urgent. A check-in text is usually enough; this isn't a "drop everything" alert.
- **Stale data**: their CGM may have disconnected, sensor expired, or their phone died. Often a non-emergency.

If you're a caregiver for someone you don't see in person regularly, agree in advance on what each alert type means and what response the patient wants.

## When the patient acknowledges before you do anything

If the patient acknowledges the alert before you can react, the escalation window may close while you're still reading the notification. The platform marks the alert as resolved on the patient's side; you'll see it in your alert history but no further action is needed.

Some caregivers find it useful to still check in even on resolved alerts ("I see you went low at 2am, you OK?") -- that's a relationship choice, not a system feature.

## Quiet hours for caregivers

If you'd rather not receive non-urgent escalations during specific hours (e.g., overnight), you can configure quiet hours on **your** end (caregiver account settings) independently of the patient's quiet hours.

**Urgent-low escalations always fire regardless of quiet hours**, by design. You cannot suppress urgent-low. This is intentional safety behavior.

## Providing context to the AI about the patient (future)

A planned feature (ROADMAP §Phase 2 Multi-Session Caregiver Escalation) lets caregivers respond to escalated alerts with context the AI incorporates into future analysis. Examples:

- "He had a hard workout this morning"
- "Stressful day at work for her today"
- "She's home sick with a fever"

The platform will log this caregiver-provided context transparently to the patient -- nothing the caregiver tells the AI is hidden from the patient. This is collaborative care, not surveillance.

This isn't in the platform today. The current alert system is one-way notification; the AI-context feature lands later.

## Why am I not receiving alerts?

Common causes:

- **The patient hasn't enabled alert escalation for this alert type** -- they control which alerts escalate to you. Ask them to check **Settings → Caregivers → click your name → escalation permissions**.
- **The escalation window hasn't elapsed** -- if the patient acknowledges within the window, escalation doesn't fire (intended behavior). You only see escalations when they don't respond.
- **Push notifications disabled** -- check in your phone's app settings that GlycemicGPT can send notifications
- **App being killed in background** -- see the battery optimization note in [Install the Android App](../mobile/install.md)
- **Patient's platform isn't reachable** -- if the patient is running on a laptop that's asleep, the platform can't fire alerts at all. This is why most caregiver setups need an always-on deployment.

## Privacy

- You see only what the patient has authorized -- you don't have access to their full account or settings
- Caregiver-side alert history is stored on the platform alongside the patient's data
- Telegram alerts go through Telegram's servers; if you'd rather avoid Telegram, use push notifications
- The platform does not share any of this with anyone else
