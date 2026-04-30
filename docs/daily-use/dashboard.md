---
title: Reading Your Dashboard
description: What each part of the GlycemicGPT dashboard shows you.
---

The dashboard is the main view in GlycemicGPT. It pulls together your latest glucose, insulin data, and trends in one place. This page explains what you're looking at.

> **The dashboard reflects the data flowing into the platform.** If a number looks wrong, the platform may be displaying what your CGM or pump reported -- including any errors. Always verify against your CGM's official app for medical decisions, and consult your healthcare provider for any clinical interpretation.

## Layout overview

The dashboard has several main areas:

- **Glucose** -- your current blood glucose, trend arrow, and recent readings chart
- **CGM summary statistics** -- average glucose, standard deviation, coefficient of variation (CV%), GMI, and CGM-active percentage over the selected window
- **AGP chart** -- Ambulatory Glucose Profile percentile bands by hour-of-day across the selected window
- **Time in Range (TIR)** -- five-bucket breakdown of how your glucose has been distributed
- **Insulin on Board (IoB)** -- how much active insulin is in your system
- **Insulin summary** -- bolus / basal breakdown, recent insulin events
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

## CGM summary statistics

A panel showing the standard CGM-statistic set computed over your selected window:

- **Average glucose** -- mean blood glucose over the window
- **Standard deviation** -- how much your glucose varies around that average
- **CV% (coefficient of variation)** -- standard deviation as a percentage of the average; a normalized variability metric clinicians use
- **GMI (Glucose Management Indicator)** -- an estimate of A1C derived from your CGM data. Different from a lab-measured A1C but useful as a between-appointments check.
- **CGM active %** -- how much of the window your CGM was actually reporting (e.g., low values indicate sensor warmups, gaps, or disconnects)

These match the standard set produced by Tidepool, Dexcom Clarity, and clinical CGM-reporting tools.

## AGP chart

The dashboard renders an [Ambulatory Glucose Profile](../concepts/glossary.md#agp----ambulatory-glucose-profile) -- the standardized clinical chart that overlays glucose curves across days to surface daily patterns, with percentile bands by hour-of-day:

- **p50** -- median glucose at each hour
- **p25 / p75** -- inter-quartile range
- **p10 / p90** -- the wider distribution

The window is selectable (typically 7 / 14 / 30 / 90 days). AGP is the lingua franca clinicians use; having it on the home dashboard means you can see what your endo would see without exporting anywhere.

> Note: a *printable* AGP-format report (the standardized PDF format clinicians often print) is a roadmap item -- the dashboard AGP visualization is what's available today.

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

Most cards (TIR, the chart) have a period selector: 24h, 7 days, 30 days. Note: time periods longer than what the platform has actually collected will show only the data that's there. If you only started running GlycemicGPT yesterday, picking "30 days" will show that one day of data over a 30-day axis -- the rest will appear empty until your platform fills in over time. This isn't a bug; the platform can't show what it hasn't received yet.

## Printing reports for your endocrinologist

Click **Reports** in the navigation to generate a printable summary for an endocrinologist appointment. You can pick the date range; the report includes Time in Range, glucose statistics, and key patterns the AI surfaced.

> The dashboard already shows an [AGP chart](#agp-chart) (the standardized clinical visualization). What's still on the roadmap is a **printable / exportable AGP-format report** in the standard PDF format clinicians sometimes print. If your endo specifically wants the standard AGP PDF, today the easier path is generating it from [Tidepool](https://www.tidepool.org/), Dexcom Clarity, or LibreView -- which all produce it in the standard format. We expect to close this gap; tracking in [ROADMAP.md](../../ROADMAP.md).

## A few honest reminders

- **The dashboard does not provide medical advice.** It shows your data and AI-generated observations, both labeled as informational.
- **Numbers can be wrong.** If a value looks impossibly high or low, your CGM or pump may have a sensor or hardware issue. Verify against the device's official app.
- **The platform stores your data on infrastructure you control.** Nothing on the dashboard is shared with anyone unless you explicitly link a caregiver (see [Caregiver overview](../caregivers/overview.md)).
