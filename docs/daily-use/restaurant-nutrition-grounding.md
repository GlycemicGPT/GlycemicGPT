---
title: Restaurant Nutrition Grounding
description: How the app grounds a branded restaurant item against the chain's own published nutrition — reference facts with a citation, still never a dose.
---

When you log a meal from a **branded restaurant or fast-food chain** — say a McDonald's Quarter Pounder or a Chipotle chicken bowl — and you confirm what the food is, the app can ground its estimate against **that chain's own published nutrition** and show you the figure with a citation, instead of relying on a photo guess alone.

> **A published carb figure is still descriptive reference data — never calculate an insulin dose or bolus from it.** Restaurant numbers vary by location, size, and preparation, the figure can be out of date, and the app might have matched the wrong menu item. Treat it as a better-sourced starting point to sanity-check against your own carb counting, and always verify before dosing.

This builds on [Meal Intelligence](meal-intelligence.md) and follows the same experimental, never-a-dose posture (it's on whenever Meal Intelligence is on).

## Reference data, not an AI guess

This is the one way the meal feature shows a number that is **not** an AI estimate. A chain's published nutrition is reference data for *its own* menu, so a grounded restaurant figure is labelled as a reference — *"Published nutrition from the restaurant's own menu data … never use it to dose or bolus"* — rather than the *"AI estimate, often wrong"* wording used for a pure photo guess.

That distinction does **not** make it safe to dose from. It is more trustworthy than a photo guess, and still descriptive only.

## You confirm the food first (identity gate)

A restaurant figure is fetched **only after you confirm what the food is**. An unconfirmed photo, or a food the app misidentified, is never "certified" with a chain citation — confirming a misidentified dish with the chain's published facts would produce an authoritatively-cited *wrong* carb count, so the app refuses to do it. If you correct the identity, grounding re-runs against your corrected name.

## How the fetch-and-cite policy works

- **On demand, one item at a time.** The app fetches *that chain's* nutrition for *that one item*, only when you log and confirm it. There is **no** pre-crawling, no bulk mirroring, and no building of a redistributable restaurant database.
- **Facts, not content.** Nutrition *facts* aren't copyrightable; the app uses the numbers, never copies a chain's page layout or images.
- **Your fetches stay yours.** A restaurant figure the app fetches for you is cached **only for your account** (owner-scoped) on your self-hosted instance — it is never pooled into a shared, redistributable mirror, and another user never sees what you fetched. (Generic USDA / Open Food Facts facts *are* shared, because those licences allow it; restaurant data is treated more conservatively.)
- **Polite by default.** The fetcher respects each site's `robots.txt`, rate-limits itself with back-off, and identifies itself with a descriptive User-Agent. A fetch only happens on your action.

These mitigations are deliberate, non-negotiable design choices. Grounding against restaurant data is a maintainer policy decision for this self-hosted, open-source project; if you run your own instance you can turn it off entirely.

## Supported chains

Restaurant grounding ships with a small set of built-in chain fetchers and grows over time. Chain menu endpoints are undocumented and change without notice, so every fetcher is **failure-tolerant**: if a chain changes its page or can't be reached, the app silently falls back to the normal vision estimate — logging never breaks, and you always still get an estimate. A chain we don't recognize is simply treated as a normal food (grounded against generic USDA / Open Food Facts, or left as a photo estimate).

> **Maintainers:** the built-in chain endpoint shapes are modelled, not continuously verified. Run the periodic live canary (see the developer runbook) to confirm each fetcher still parses real responses; a broken fetcher should degrade to vision-only, never break logging.

## Optional: bring your own FatSecret key

For broader commercial restaurant coverage, an operator can supply their **own** [FatSecret Platform](https://platform.fatsecret.com/) credentials (`fatsecret_consumer_key` / `fatsecret_consumer_secret`). This is entirely optional and **no shared key is ever shipped** — the app is blank until you add yours. To honour FatSecret's terms, a FatSecret-sourced value is cached for **at most 24 hours** and otherwise re-queried, and it is never shared across users.

## Turning it off

Restaurant grounding is on when Meal Intelligence is on, and can be disabled on its own with `restaurant_grounding_enabled=false` (restaurant-chain fetching is skipped, and grounding falls back to the normal USDA / Open Food Facts / vision path). Because it makes an outbound request to the chain on your behalf, leave it off if you don't want that.

## The bottom line

Grounding a restaurant item gives you a **better-sourced number with a citation** — published reference data instead of a photo guess. It is still descriptive, can still be wrong for your specific order, and is still **never** a dose. Count your carbs and decide your insulin the way you and your healthcare provider do today.
