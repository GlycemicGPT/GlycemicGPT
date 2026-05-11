---
title: Integrations
description: Connect GlycemicGPT to Dexcom, Tandem, Nightscout, and other data sources that flow your diabetes data into the platform.
---

GlycemicGPT is designed to sit alongside the tools you already use -- your CGM's app, your pump's cloud, and (if you have one) your Nightscout instance. Integrations are how the platform gets your data in.

This page is the index. Each integration with a longer setup flow has its own page; the short ones are documented in full here.

> **One-line mental model.** An integration is a connection that pulls your diabetes data into GlycemicGPT -- from your CGM cloud, your pump cloud, or your Nightscout site. Set it up once in **Settings → Integrations**; the platform polls on a schedule from there.

## What's available

| Integration | What it brings in | Use it if you... | Setup |
|---|---|---|---|
| [Dexcom](./connecting-dexcom.md) | Real-time glucose | Have a Dexcom G6 / G7 / ONE+ | Dexcom email + password |
| [Tandem Cloud](./connecting-tandem-cloud.md) | Pump history, boluses, basal, IoB | Have a t:slim X2 or Mobi | Tandem email + password |
| [Nightscout](#nightscout) | CGM entries, treatments, devicestatus, profile | Already run a Nightscout site -- often with a CGM we don't speak directly to (Libre, Eversense, Medtronic, etc.) | Nightscout URL + API_SECRET |

Everything lives at **Settings → Integrations** on the dashboard.

---

## Nightscout

If you already self-host (or use a hosted) [Nightscout](https://nightscout.github.io/), GlycemicGPT can read your CGM entries, pump treatments, devicestatus, and profile straight from your Nightscout site. This is the easiest path for CGMs we don't speak to directly (Libre, Eversense, Medtronic), and for closed-loop users on Loop / AAPS / Trio whose loop already uploads to Nightscout.

> **Why connect Nightscout?** Anything that flows into Nightscout -- glucose entries, boluses, basal changes, loop status, profile settings -- flows into GlycemicGPT through this connection. It's the universal onramp for the diabetes-OSS ecosystem.

### Before you start, you need

- A working Nightscout site you can sign in to. The URL looks like `https://your-name.up.railway.app` or `https://your-name.onrender.com`.
- Your Nightscout **API_SECRET** (the long string from your Nightscout config, used for authenticated reads), **or** a bearer token issued by your deployment.
- GlycemicGPT running and you signed in to your dashboard.

### Smart onboarding (recommended)

GlycemicGPT ships a guided 5-step wizard that connects to your Nightscout, reads your existing profile, and pre-fills your GlycemicGPT settings (target range, ISF, carb ratio, basal schedule, DIA) so you don't start from a blank dashboard.

#### How to start the wizard

1. Go to **Settings → Integrations** on the dashboard.
2. Open the **Third-Party Integrations → Nightscout** section.
3. Click **Start smart onboarding**.

#### What each step does

**Step 1 -- Credentials.** Type a friendly name (e.g. "Home Loop"), your Nightscout URL, and your API_SECRET / bearer token. GlycemicGPT tests the connection before reading anything. If the test fails, fix the URL or credential and try again -- nothing else has been saved yet.

**Step 2 -- Reading your Nightscout.** The wizard:

1. Probes your Nightscout to estimate how much data you have (entries count, treatment count, which uploaders are detected, server version).
2. Pulls your first sync so the connection is populated.
3. Reads your default profile (the one your Nightscout is configured to use).

This usually takes a few seconds. On a Nightscout with months of treatments it can take up to half a minute -- the wizard will tell you it's still working.

**Step 3 -- Review what we found.** A diff table shows, for each setting:

- What GlycemicGPT has now (your current value).
- What your Nightscout profile suggests (the proposed value).
- A **Use this?** checkbox.

The settings covered:

- **Target low** / **Target high** -- your glucose target range, in mg/dL.
- **DIA (Duration of Insulin Action)** in hours.
- **Basal schedule** -- the time-of-day basal rate table from your profile.
- **Carb ratio schedule** -- carbs-per-unit, time-of-day.
- **ISF (Insulin Sensitivity Factor) schedule** -- mg/dL per unit, time-of-day.

For each numeric row you can type a different value in the **override** box to use instead of the proposed value. Empty box = use the proposed value. The wizard validates that overrides are positive numbers -- if you typo a negative or zero, Apply stays disabled until you fix it.

Schedule rows have a **Preview** button that expands a table showing every segment from your Nightscout profile so you can see exactly what would land.

Below the table, **Import history for** picks how far back to pull entries on the first sync: 1 day, 7 days, 30 days, 90 days, or all available.

> **Insulin type is not auto-imported.** GlycemicGPT needs to know what insulin you're on (Humalog, Novolog, Fiasp, Lyumjev, etc.) to compute IoB curves correctly. The wizard intentionally doesn't guess -- pick yours under **Settings → Insulin** once after the wizard finishes.

> **mmol/L users.** If your Nightscout reports `units: mmol`, the wizard automatically converts target ranges and ISF to mg/dL before they land in GlycemicGPT and surfaces a banner so you can see the conversion happened. GlycemicGPT stores glucose values in mg/dL internally regardless of how you view them.

> **What if your Nightscout reports unrecognized units?** A warning banner appears and the wizard refuses to import glucose-domain settings (target range, ISF) until you tick a confirmation box stating your values are actually in mg/dL. If they're actually mmol/L and you tick the box, your targets and ISF will be 18x off -- so read carefully.

**Step 4 -- Importing.** GlycemicGPT writes the settings you chose and kicks the first sync. This step can take up to 20 seconds on a busy Nightscout.

**Step 5 -- Done.** A summary lists which settings landed and how many records the first sync imported. From here you can jump to the dashboard to see your data, or back to **Settings → Integrations** to add a second Nightscout connection (e.g. for a child or partner you also follow).

### Expert mode (manual setup)

The original credential-only form is preserved under **Settings → Integrations → Nightscout → Expert mode (manual setup)**. It connects without the profile read or the diff table -- useful if you're scripting setup, only want to import data without changing settings, or you've already imported once and just want a second connection.

### What you can do after connecting

- **Sync now** -- force a fetch immediately instead of waiting for the scheduled tick.
- **Sync every** -- a quick selector for how often GlycemicGPT polls your Nightscout (1m / 5m / 15m / 30m / 60m). Default 5m balances freshness against your Nightscout's resource budget.
- **Test** -- verifies the URL / credential still authenticates without doing a full sync.
- **Delete** -- removes the connection. Data already imported into GlycemicGPT stays in your local store; only future syncs stop.

You can have **more than one** Nightscout connection -- common pattern for caregivers who follow multiple people, each with their own Nightscout.

### What flows in

| Nightscout collection | What lands in GlycemicGPT |
|---|---|
| `entries` | CGM readings on your glucose chart, AGP, Time in Range |
| `treatments` (boluses, carbs) | Bolus markers on the chart, IoB calculation, carb history |
| `treatments` (basal changes) | Basal schedule history |
| `devicestatus` | Loop / AAPS / Trio status, pump battery / reservoir if reported |
| `profile` | Target range, ISF, carb ratio, basal, DIA (during the wizard) |

### Troubleshooting

- **"Could not resolve host."** Your Nightscout URL is unreachable from where GlycemicGPT runs. Double-check the URL is the one you sign in at, including `https://`, and that the instance is up.
- **"401 / 403."** API_SECRET or token is wrong, or your Nightscout has scope-restricted authentication. Try regenerating a token from your Nightscout admin page.
- **The chart still has gaps after a sync.** A known limitation -- if your Nightscout's uploader had a disconnect and backfilled into Nightscout after our sync cursor advanced, we may not pick those records up. Workaround: delete and re-create the connection with a wider initial sync window, or contact support. Tracked in [GitHub issue #598](https://github.com/GlycemicGPT/GlycemicGPT/issues/598).
- **No profile detected.** Some Nightscout sites have profile auto-discovery turned off. You can still use the connection for data import; you'll need to set glucose / insulin settings manually under **Settings**.

---

## Adding more

The integration list grows. The current roadmap targets are LibreLinkUp (Freestyle Libre cloud), Tidepool (cloud upload and clinical reports), and broader pump bridges. Watch [ROADMAP.md](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/ROADMAP.md) for what's coming and approximate timing.

If your CGM, pump, or cloud platform isn't on the list yet, the workaround that already works **today** is to upload to a Nightscout instance (often via [xDrip+](https://github.com/NightscoutFoundation/xDrip), [LibreLinkUp-Uploader](https://github.com/timoschlueter/nightscout-librelink-up), or your loop's built-in uploader) and then connect that Nightscout here. Anything that flows into Nightscout flows into GlycemicGPT.

## Still stuck?

- Watch the relevant section of the [Troubleshooting guide](../troubleshooting/index.md).
- Ask on [Discord](https://discord.gg/QbyhCQKDBs) -- include the integration name, what step you're on, and any error message you see.
- File an issue at [github.com/GlycemicGPT/GlycemicGPT/issues](https://github.com/GlycemicGPT/GlycemicGPT/issues/new/choose). Include your platform version and how you deployed (Docker / k8s / self-built).
