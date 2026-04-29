---
title: Reading Your Dashboard
description: What each part of the GlycemicGPT dashboard shows you.
---

The dashboard is the main view in GlycemicGPT. It pulls together your latest glucose, insulin data, and trends in one place. This page explains what you're looking at.

> **The dashboard reflects the data flowing into the platform.** If a number looks wrong, the platform may be displaying what your CGM or pump reported -- including any errors. Always verify against your CGM's official app for medical decisions, and consult your healthcare provider for any clinical interpretation.

## Layout overview

The dashboard has a few main areas:

- **Glucose** -- your current blood glucose, trend arrow, and recent readings
- **Time in Range (TIR)** -- how much of the past day / week you've been in your target glucose range
- **Insulin on Board (IoB)** -- how much active insulin is in your system
- **Pump status** -- battery, reservoir, basal rate (if you have a pump connected)
- **Recent activity** -- a chronological feed of glucose readings, boluses, alerts, and AI insights

The exact arrangement depends on your screen size -- on phones it stacks vertically, on larger screens it spreads out.

## Glucose

The big number at the top is your most recent glucose reading. Below it:

- **Trend arrow** -- the direction your glucose is moving (rising, falling, steady)
- **Last reading time** -- when this value was recorded. If it's more than a few minutes old, your data flow may have stalled -- see [BG isn't updating](../troubleshooting/bg-not-updating.md).
- **Glucose chart** -- typically the last few hours of readings, with shaded bands showing your target range

Your target range is configured in **Settings → Glucose Range**. Defaults are typical clinical guidelines; ask your healthcare provider what targets they recommend for you.

## Time in Range (TIR)

A bar showing how your glucose has been distributed across these zones over the selected time window:

- **In range** (target zone)
- **Above range** (high)
- **Below range** (low)
- **Severely below** (urgent low)

You can change the time window with the period selector. Longer windows are useful for talking with your endocrinologist; shorter windows are useful for "how am I doing today."

> **Time in Range is a guideline, not a goal in itself.** Your endocrinologist may have specific recommendations for your TIR targets based on your treatment plan.

## Insulin on Board (IoB)

The amount of bolus insulin still active in your system, calculated from your recent boluses and your insulin action time. The value updates as time passes (insulin decays).

If you have a Tandem pump connected, GlycemicGPT reads IoB directly from the pump's onboard calculation. If you're only using a CGM (no pump), IoB shows zero or "not available."

## Pump status

Visible only when you have a pump connected. Cards show:

- **Battery** -- the pump's remaining battery percentage
- **Reservoir** -- how much insulin is left in the cartridge / pod
- **Basal rate** -- your current basal delivery rate

If any of these are missing or stale, the data flow from your pump has likely stalled -- see [BG isn't updating](../troubleshooting/bg-not-updating.md).

## Recent activity

A chronological feed of what's been happening:

- New glucose readings as they come in
- Boluses you delivered (read from your pump)
- Alerts that fired
- AI insights / daily briefs

The feed updates in real time -- you don't need to refresh.

## Period selector

Most cards (TIR, the chart) have a period selector: 24h, 7 days, 30 days. Note: time periods longer than 7 days require the data to actually exist in the platform's database. If you only started running GlycemicGPT yesterday, "30 days" will only show the data the platform has.

## Printing reports for your endocrinologist

Click **Reports** in the navigation to generate a printable summary for an endo appointment. You can pick the date range; the report includes TIR, glucose statistics, and key patterns the AI surfaced. See the report page for details (coming soon in [AI-Enhanced Endo Reports](../concepts/glossary.md) -- ROADMAP §Phase 2).

## A few honest reminders

- **The dashboard does not provide medical advice.** It shows your data and AI-generated observations, both labeled as informational.
- **Numbers can be wrong.** If a value looks impossibly high or low, your CGM or pump may have a sensor or hardware issue. Verify against the device's official app.
- **The platform stores your data on infrastructure you control.** Nothing on the dashboard is shared with anyone unless you explicitly link a caregiver (see [Caregiver overview](../caregivers/overview.md)).
