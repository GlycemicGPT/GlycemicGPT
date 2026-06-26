---
title: Meal Intelligence (Photo Carb Estimates)
description: Snap a photo of a meal to get a rough carb range — a starting point, never a dose.
---

Meal Intelligence lets you take a photo of a meal and get an AI **estimate** of its carbohydrate content as a range (for example, "≈ 40–55 g carbs"), with a confidence signal. You can correct the estimate, save foods you eat often, and the AI can reference your logged meals in chat and daily briefs.

> **Photo carb estimates are AI guesses, frequently wrong, and a rough starting point only — never calculate an insulin dose or bolus from them.** The AI looks at an image and *guesses*; it regularly misjudges portions and sometimes misidentifies the food entirely. Treat every number as a ballpark to sanity-check against your own carb counting. Always verify carbs yourself before dosing, and consult your healthcare provider about your diabetes management.

This is an **experimental feature**, **on by default**, that you can turn off (or back on) at any time from Settings. It is **not** FDA-cleared and is **not** a carb-counting authority.

## What it does

1. **Estimate** — you take or pick a meal photo; the AI returns a carb **range** and a confidence level (low / medium / high).
2. **Correct** — if the estimate is off, you correct it. Your correction becomes the truth the app remembers — it never silently overwrites your number with a guess.
3. **Save** — foods you eat often can be saved so a re-photographed meal recognizes them ("you've logged this before") instead of re-guessing.
4. **Aware** — when you've logged meals, chat and daily briefs can reflect them back to you ("you logged a high-carb dinner — how did that sit with you?"). They never tell you how much insulin to take.

## How it's built to be safe

The feature is designed so a guess can never quietly turn into a dose:

- **A range, not a single confident number.** Real plates are uncertain; a single integer invites you to dose off it.
- **Confidence comes from disagreement, not the model's self-rating.** The same photo is sampled several times; the spread between answers drives the confidence. (A model's own "I'm confident" score does not track accuracy and is never shown as a safety signal.) A wide spread is shown plainly — "this could be 40 g or 90 g, we're not sure."
- **You confirm what the food is** before the app grounds it against nutrition data, so a misidentified food can't be "certified" with an authoritative-looking citation. For branded restaurant items this can cite the chain's own published nutrition — see [Restaurant Nutrition Grounding](restaurant-nutrition-grounding.md).
- **Carb estimates never flow into insulin-on-board, safety limits, or any dosing math.** They are descriptive notes, structurally isolated from the dosing engine.
- **Every screen that shows a carb estimate carries a persistent reminder** — *"Rough estimate — an AI guess that's often wrong. Never use it to calculate an insulin dose or bolus."*

## Known limitations

- **Misidentification is the most common error** — look-alike foods (a Linzer torte read as a Bakewell tart, crème catalana as crème brûlée) can be confidently wrong.
- **Run-to-run variance** — the same photo can yield different numbers; the confidence range is meant to surface that, not hide it.
- **Accuracy is honest, not perfect** — on a labeled test set the estimate was within a useful band most of the time, but tail cases can be far off. This is why it stays experimental and why you must verify.

## Turning it on or off

Meal Intelligence is **on by default**. You control it per-account from **Settings → Meal Intelligence** in both the web app and the phone app — turn it off to hide the meal surfaces (the "Log a meal" button, the Meals area, and the photo-capture flow), or back on to restore them. There's no environment variable or operator step: it's an ordinary in-app preference, like your glucose display unit, and your choice syncs across your devices.

To actually produce estimates the feature needs a **vision-capable AI provider** configured — with it on but no vision provider, the surfaces appear but a photo estimate returns a clear "not available" error rather than a guess. Because it sends a food photo to your configured AI provider, the same BYOAI data-handling rules apply as the rest of the app — review your provider's policy.

If you run a **local model**, note that meal photos have a higher quality bar than text chat: an unverified local model is refused for photo estimates (with a clear message) rather than allowed to produce a low-quality guess. See [Local AI Vision](../concepts/local-ai-vision.md) for which models clear the bar and why cloud is the verified path for photos today.

## The bottom line

A carb estimate from a photo is a **guess about a picture**, not a measurement and never a dose. Use it to get a baseline, correct it when it's wrong, and **count your carbs and decide your insulin the way you and your healthcare provider do today.**
