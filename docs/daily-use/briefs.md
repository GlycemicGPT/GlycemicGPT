---
title: Daily Briefs
description: AI-generated summaries of your day, automatically.
---

A daily brief is an AI-generated summary of what happened with your glucose, insulin, and patterns over the past day. Today briefs run on a daily cadence; weekly / longer cadences are a roadmap item but not shipped yet. They show up in your dashboard automatically -- you don't have to ask for them.

> **Briefs are informational summaries, not medical advice.** They highlight patterns the AI noticed -- often things worth discussing with your healthcare provider. They are not a clinical assessment.

## What's in a brief

The AI brief generator passes your data (Time in Range, average glucose, low / high counts, Control-IQ correction count, total insulin, optional pump profile, optional IoB context) to your configured AI provider with a prompt asking for a plain-language summary that touches on patterns, post-meal spikes, overnight trends, and meaningful Control-IQ activity.

Because the brief is AI-generated prose rather than a fixed-template report, exact sections are not guaranteed -- the AI structures the response based on what your data actually shows. A typical brief mentions:

- **Time-in-Range performance** for the day
- **Notable highs and lows** -- when they happened and possible context
- **Insulin / Control-IQ patterns** the AI noticed
- **Overnight behavior** if there's anything interesting to note
- **Suggestions for follow-up** when the AI sees a pattern worth pulling on

Briefs are written in plain language, not clinical jargon -- they're meant to be easy to read.

## When briefs are generated

You configure this in **Settings → Briefs**:

- **Enable / disable** the daily brief
- **Time of day** -- when the daily brief gets generated (default: morning)
- **Timezone** -- so the time-of-day setting reflects your local time
- **Delivery channel** -- in-app (web only), Telegram (if configured), or both

If the brief is set to "morning" and there's no glucose data for the previous day, the brief will say so -- the AI can't summarize what isn't there.

## Where to read them

- **In the dashboard** -- a Briefs panel on the home screen and a dedicated page
- **Telegram** (if configured) -- the full brief delivered as a message

> Note on push notifications: brief delivery to a phone via push notification (rather than Telegram) is a roadmap item, not shipping today. If you want briefs on your phone today, the path is Telegram.

## Manually generating a brief

If you want a brief outside the schedule (e.g., to summarize a specific period before an endo appointment), go to **Briefs → Generate brief** and pick the date range. The platform queues the request and the brief appears within a minute or two.

## Briefs are different from AGP

GlycemicGPT does render an [AGP (Ambulatory Glucose Profile)](../concepts/glossary.md#agp----ambulatory-glucose-profile) chart on the home dashboard -- percentile bands by hour-of-day across a configurable window. AGP is the standardized clinical chart your endocrinologist most consistently knows how to read, and you can see one in GlycemicGPT today.

Daily briefs are a *different artifact*: AI-written prose summaries of recent activity, focused on what's interesting or unusual rather than the structured clinical picture AGP gives. They have different jobs:

- **AGP (on the dashboard)** -- deterministic percentile bands, fixed statistics, the clinical-format view
- **Briefs** -- prose for self-reflection, with the AI chat behind them for follow-up questions

You'll often want both: AGP for "how am I doing structurally over time," briefs for "what stood out yesterday and is there a thread to pull on."

> Note: a printable AGP-style report (the kind you'd hand to your endocrinologist) is a roadmap item -- the dashboard AGP is the visualization, but the standardized exported / printable report format is still being built.

## Brief quality depends on data quality

A brief is only as useful as the data the AI has to work with:

- **Sparse glucose data** -- if your CGM was in warmup or had connection gaps, the brief will be thinner
- **No insulin data** -- if you're using GlycemicGPT for monitoring only and don't have a pump connected, briefs focus on glucose patterns and don't mention insulin
- **Recent setup** -- briefs that try to identify patterns need at least a few days of historical data

The platform does what it can with what it has -- briefs explicitly note when data was missing.

## Privacy

- Briefs are stored on your platform's database alongside your other data
- The AI provider you configured generates briefs by reading your data and writing the summary -- the data goes to the provider during generation (see [Privacy](../concepts/privacy.md))
- Briefs are not shared with anyone unless you've linked a caregiver who has brief-read permission (see [Caregivers](../caregivers/overview.md))

## Disabling briefs

If you'd rather not have automated briefs, go to **Settings → Briefs** and toggle them off. You can still generate briefs manually when you want them.

## Why is my brief wrong / weird / missing things?

Same root causes as any AI quality issue:

- **Sparse / weird data** -- if your CGM had a 6-hour gap, the brief might say "no overnight data available"
- **Smaller models hallucinate more** -- using a premium model (Claude Opus, GPT-4-class) gives sharper briefs
- **The AI just gets it wrong sometimes** -- AI is not infallible. Use briefs as starting points for conversations with your endo, not gospel.

A hallucination-feedback mechanism (so you can flag a bad brief and have it regenerated from a fresh session) is on the roadmap -- see [ROADMAP.md](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/ROADMAP.md) §Phase 1 AI Engine 2.0.
