---
title: Local AI Vision (Meal Photos)
description: Which local models can do meal-photo carb estimation well enough — and why most are turned off until proven.
---

If you run a local model (Option 5 in [BYOAI](byoai.md)) and you've turned on
[Meal Intelligence](../daily-use/meal-intelligence.md), this page explains why a
meal photo may say *"this model isn't verified for carb estimation"* — and what
clears that bar.

> **Photo carb estimates are AI guesses, frequently wrong, and a rough starting
> point only — never use one to calculate an insulin dose or bolus.** This page
> is about which models are *good enough to bother showing you a guess at all*.
> It does not change the rule that you verify carbs yourself before dosing.

This is an **experimental (alpha)** area. It is **not** FDA-cleared and **not** a
carb-counting authority.

## Why local vision is gated, but cloud isn't

Cloud vision (Claude / OpenAI) has been measured on a labelled food set and
behaves well enough to build on. An arbitrary local model has **not**, and the
risk is specific, not hand-wavy:

- **It can swing wildly on the same photo.** Ask a weak model about one plate
  five times and it may answer 30 g once and 90 g the next. The dangerous draw is
  the high one — that's the acute-hypo risk, and an *average* hides it.
- **It can confidently misidentify the food.** Naming a crème catalana a crème
  brûlée, or a Bakewell tart a Linzer torte, is upstream of every carb number. A
  smaller model gets this wrong far more often than a frontier one.

A model that is *accurate on average* can still fail both of these. So rather than
let an unproven local model produce a silent, possibly-dangerous estimate, the app
**refuses** and tells you why. Refusing is safer than guessing badly.

## The bar a local model must clear

A local model is considered good enough for meal photos only when, on a set of
simple single foods, it is:

- **Reproducible** — repeated looks at the same photo don't swing much (bounded
  run-to-run variation and per-photo spread).
- **Right about *what the food is*** — it correctly names simple foods nearly all
  the time (misidentification is what dominates carb error).
- **Accurate enough on average** — within a sensible grams band. This is the
  *floor*, not the headline; reproducibility and identity come first.
- **Safe** — it never emits dosing/insulin language.

Reproducibility and identity are weighted above raw accuracy on purpose: a model
that is right on average but erratic, or confidently wrong about the food, is the
one that causes harm. The exact thresholds and the measurement method live with
the project's evaluation harness (`evals/vision_carb/`), which is the same
instrument used to measure the cloud baseline — so local and cloud numbers are
directly comparable.

## Which local models clear it today

**None yet — on first-party hardware.** No local vision model has been certified
through the harness on the project's own hardware, so **meal photos are gated for
every local model**: you'll get the clear "not verified" message rather than a
low-quality estimate.

For meal photos today, **use a cloud AI provider** (the verified path). Your local
model still works for everything else (AI chat, briefs) — only the photo
carb-estimate is gated.

Candidate model families worth testing, if you want to help establish the bar
(none endorsed — these are *starting points to evaluate*, not recommendations):

- **LLaVA** (e.g. `llava:13b`)
- **Llama 3.2 Vision** (e.g. `llama3.2-vision:11b`)
- **Qwen-VL** (e.g. `qwen2.5-vl:7b`)

Smaller (7B–8B) vision models tend to miss portion nuance and misidentify
look-alikes; if you have the VRAM, the larger variants are the more promising
place to start. As with the rest of BYOAI, **please report what you find** so the
project can build an evidence-based list.

## Verifying a local model yourself (advanced)

If you're technically inclined and run local models, you can measure a candidate
against the same bar the project uses. In the repository:

```bash
# Source the licence-clean evaluation images (easy + adversarial look-alikes).
python evals/vision_carb/fetch_images.py \
    --manifest dataset/manifest.json dataset/adversarial.json

# Serve a candidate model under Ollama, then benchmark it at N>=5 and gate on the
# pass-bar (it exits non-zero unless the model clears the bar).
ollama pull llava:13b
python evals/vision_carb/harness.py \
    --base-url http://localhost:11434 --model llava:13b --no-auth \
    --manifest dataset/manifest.json dataset/adversarial.json \
    --repeats 5 --enforce-pass-bar
```

This is a live run on your own machine — it costs compute and is not part of the
app. A model that passes is a candidate to enable; enabling it in the product is a
separate, deliberate maintainer step.

## Configuring a local model

See [BYOAI Option 5](byoai.md) for the full setup. In short: **Settings → AI
Provider → OpenAI-compatible**, set the **Base URL** (e.g.
`http://localhost:11434/v1` for Ollama), the **Model name**, an **API key** if the
endpoint needs one, and — for "thinking" models — raise **Max response tokens** so
reasoning tokens don't truncate the answer. A local endpoint on a private address
also requires the deployment to allow private AI URLs.

## How this stays safe regardless

The capability gate is one layer; the meal-photo safety design holds whichever
model you use:

- Estimates are a **range with an empirical confidence**, never a lone confident
  number, and never the model's self-reported confidence.
- A wide spread is shown plainly as uncertainty, not smoothed over.
- Carb estimates are **structurally isolated** from insulin-on-board, safety
  limits, and any dosing math.
- Every screen with a carb number carries the persistent reminder — *never use it
  to dose or bolus.*

The bottom line: a verified model gets you a *better starting point*, not a number
you can dose off. Verify carbs yourself, and talk to your healthcare provider
about your diabetes management.
