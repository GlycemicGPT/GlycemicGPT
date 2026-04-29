---
title: Daily Briefs
description: AI-generated summaries of your day, automatically.
---

A daily brief is an AI-generated summary of what happened with your glucose, insulin, and patterns over the past day (or week, or other configured interval). They show up in your dashboard automatically -- you don't have to ask for them.

> **Briefs are informational summaries, not medical advice.** They highlight patterns the AI noticed -- often things worth discussing with your healthcare provider. They are not a clinical assessment.

## What's in a brief

A typical daily brief includes:

- **Time in Range summary** -- how the day compared to your target ranges
- **Notable highs and lows** -- when they happened, possible context (meal timing, missed bolus, etc.)
- **Insulin patterns** -- bolus timing, frequency, any unusual patterns
- **Sleep / overnight** -- how your glucose behaved overnight
- **Suggestions for follow-up** -- questions the AI thinks are worth asking your endo, or patterns to watch in the next few days

Briefs are written in plain language, not clinical jargon -- they're meant to be easy to read.

## When briefs are generated

You configure this in **Settings → Briefs**:

- **Frequency** -- daily, weekly, or both
- **Time of day** -- when the daily brief gets generated (default: morning)
- **Delivery channels** -- in-app only, push notification, or Telegram (if configured)

If the brief is set to "morning" and there's no glucose data for the previous day, the brief will say so -- the AI can't summarize what isn't there.

## Where to read them

- **In the dashboard** -- a Briefs panel on the home screen and a dedicated page
- **Push notification** (if enabled) -- a short summary, click to read the full brief in the app
- **Telegram** (if configured) -- the full brief delivered as a message

## Manually generating a brief

If you want a brief outside the schedule (e.g., to summarize a specific period before an endo appointment), go to **Briefs → Generate brief** and pick the date range. The platform queues the request and the brief appears within a minute or two.

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
- **Smaller models hallucinate more** -- using a frontier model (Claude Opus, GPT-4-class) gives sharper briefs
- **The AI just gets it wrong sometimes** -- AI is not infallible. Use briefs as starting points for conversations with your endo, not gospel.

A hallucination-feedback mechanism (so you can flag a bad brief and have it regenerated from a fresh session) is on the roadmap -- see [ROADMAP.md](../../ROADMAP.md) §Phase 1 AI Engine 2.0.
