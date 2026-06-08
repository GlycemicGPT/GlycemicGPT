---
title: Connecting Your Medtronic Pump (CareLink)
description: How GlycemicGPT pulls Medtronic pump and CGM data from CareLink — continuous sync and one-time import.
---

GlycemicGPT can bring your Medtronic pump and sensor data in from **Medtronic CareLink** without linking your pump to a phone over Bluetooth. This is an onramp for Medtronic users: your CGM readings, boluses, carbs, and fingersticks flow into GlycemicGPT so the dashboard and AI analysis have the same data CareLink shows.

> **Prefer to skip the cloud?** If you use the GlycemicGPT mobile app and have a MiniMed 680G / 770G / 780G, you can [pair the pump directly over Bluetooth](./connecting-medtronic-pump.md) (beta) — no CareLink account needed. This page covers the **CareLink cloud** path; the two are independent.

There are **two ways** to bring Medtronic data in, and you can use either or both.

> **Continuous vs one-time, what's the difference?**
>
> | Path | What it does | Repeats? |
> |---|---|---|
> | **Continuous sync** (CarePartner) | Keeps GlycemicGPT updated on a schedule, hands-off after a one-time setup | Yes — every ~30 min |
> | **One-time import** (historical) | Pulls a date range you pick, once | No — run it again whenever you want more history |
>
> Most users set up **continuous sync** for ongoing data and use the **one-time import** to backfill history from before they connected.

> **Why a browser step is involved (both paths):**
>
> Medtronic's sign-in only completes in a real web browser — it requires a captcha that can't be automated. So both paths start with you signing in to Medtronic once on your own computer. GlycemicGPT never sees your Medtronic password; it only receives the short-lived access token your browser produces after you sign in.

---

## Continuous sync (CarePartner)

This keeps GlycemicGPT updated automatically. After a one-time setup, a background job pulls your recent data from Medtronic on a schedule — no phone, no app, nothing to re-run day to day.

> **Before you start, you need:**
>
> - A Medtronic pump + CGM whose data shows up in Medtronic's **CareLink / CarePartner** (the MiniMed Mobile or CareLink app already uploading your pump to Medtronic's cloud)
> - Your CareLink username and password
> - A desktop browser installed (Chrome, Edge, Brave, or Chromium)
> - GlycemicGPT running and you signed in

### What it pulls

- **Sensor glucose** (your CGM trace) — drives the dashboard, time-in-range, and alerts
- **Boluses** (insulin delivered)
- **Carbs** (meal entries)
- **Fingerstick BG** (calibrations / manual readings)

> v1 connects your **own** Medtronic account. Following *someone else's* pump as a care partner (e.g. a parent following a child) is planned but not available yet. SmartGuard auto-basal micro-boluses are not yet mapped either — basal is shown as the scheduled rate. These are documented limitations while the data mapping is validated against live active-pump accounts.

### Setting it up

In your GlycemicGPT dashboard:

1. Go to **Settings → Integrations → Cloud Sync** and find **Medtronic CareLink**.
2. Pick your **region** (United States, or Europe / International for UK, EU, Australia, and other non-US accounts — one Medtronic OUS account covers the whole region).
3. Enter your **CareLink username** and click **Connect with CareLink**.
4. GlycemicGPT shows a **one-time setup command**. Copy it and run it in a terminal on your own computer (macOS/Linux) or PowerShell (Windows). It downloads a small helper **from your own GlycemicGPT instance** — there's no third-party download.
5. The helper opens your browser to Medtronic's sign-in. **Sign in and solve the captcha.**
6. That's it. The helper hands the resulting login back to GlycemicGPT and exits. Your screen will show the connection as active.

Under the hood, GlycemicGPT stores an encrypted **refresh token** (never your password) and uses it to keep itself authorized. If Medtronic's sign-in ever expires, the connection shows as **Disconnected** and you re-run the one-time setup.

### How often does it sync?

Every **30 minutes** by default. You can change the interval (15 minutes to 24 hours) in the Medtronic CareLink section. Syncing more often than Medtronic's own cloud updates doesn't get you fresher data.

### Why a setup command instead of a button?

Because Medtronic's login only works in a browser with a captcha, and the app it's built for is a mobile app, there's no way for a server to complete the sign-in for you. The helper runs the browser step **on your machine** so the captcha is yours to solve, then relays only the resulting login code. The refresh token never leaves your GlycemicGPT backend. (A Python command-line fallback is offered under "Advanced" for users who'd rather not download a binary.)

---

## One-time import (historical backfill)

Use this to pull a specific date range once — for example, to backfill the weeks before you set up continuous sync.

### How it works

1. In **Settings → Integrations → Cloud Sync → Medtronic CareLink**, find the **import** card.
2. Sign in to CareLink in the browser window it opens, solving the captcha.
3. Click the **GlycemicGPT bookmarklet** (a one-time bookmark you drag in). It reads the short-lived CareLink token from your signed-in session and hands it back to GlycemicGPT (or copies it for you to paste).
4. GlycemicGPT shows the **date range available** in your CareLink account. Pick a window and click **Import**.

You can import up to **31 days at a time**. To pull more history, run the import again for an earlier window. The token is used **only for that import** and is never stored.

### Continuous sync vs one-time import — which counts?

Both write to the same place, so they don't conflict — GlycemicGPT de-duplicates readings, so importing a range you already have just does nothing. Use continuous sync for "keep me current" and one-time import for "go fetch the past."

---

## Privacy

- GlycemicGPT **never receives your Medtronic password.** You sign in to Medtronic directly; GlycemicGPT only gets the short-lived token your browser produces.
- For continuous sync, the stored refresh token, username, and account id are **encrypted at rest** (using your `SECRET_KEY`).
- Data flows in one direction only: from Medtronic's cloud into GlycemicGPT. GlycemicGPT never pushes anything back to Medtronic.
- See [Privacy](../concepts/privacy.md) for the full picture.

## Stability of the CareLink path

Honest disclosure: Medtronic does not publish a developer API. GlycemicGPT's CareLink integration is built from community reverse-engineering work (notably [xDrip+](https://github.com/NightscoutFoundation/xDrip), GPL-3.0, credited in `THIRD_PARTY_LICENSES.md`).

What this means in practice:

- **Medtronic can break it.** Auth flows and data shapes can change without notice; when they do, expect a lag of days to weeks for a fix.
- **The data mapping is still being validated against live pumps.** Authentication and data transport are proven on real accounts, but the precise mapping of boluses/carbs from live active-pump data is still being confirmed. Treat continuous sync as **beta** and sanity-check important values against CareLink itself.
- **The one-time browser + captcha step is Medtronic's, and unavoidable** for everyone — there's no way around it.

## When the integration breaks

- **Continuous sync shows Disconnected:** your Medtronic sign-in expired or your password changed. Re-run the one-time setup command.
- **Import fails or shows no range:** sign in at the CareLink website to confirm your account is in good standing and that it actually has data for the dates you want.

## Still stuck?

If the connection says active but data isn't appearing, see [BG isn't updating](../troubleshooting/bg-not-updating.md).
