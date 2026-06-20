---
title: Connecting Your Omnipod (via Glooko)
description: How GlycemicGPT pulls Omnipod pump and CGM data from Glooko — continuous sync and one-time import.
---

GlycemicGPT can bring your **Omnipod** pump data in from **Glooko** without linking your Pod to a phone over Bluetooth. Insulet's Omnipod 5 uploads its data to Glooko only — there is no separate Omnipod cloud to read — so Glooko *is* the onramp. Your basal, boluses, and pod changes (and your sensor glucose, when your setup streams it to Glooko) flow into GlycemicGPT so the dashboard and AI analysis have the same data Glooko shows.

There are **two ways** to bring Omnipod data in, and you can use either or both.

> **Continuous vs one-time, what's the difference?**
>
> | Path | What it does | Repeats? |
> |---|---|---|
> | **Continuous sync** | Keeps GlycemicGPT updated on a schedule, hands-off after you connect | Yes — every ~30 min |
> | **One-time import** (historical) | Pulls your history once, back to when your Pod started uploading | No — run it again whenever you want more history |
>
> Most users set up **continuous sync** for ongoing data and use the **one-time import** to backfill history from before they connected. Both live in the same card.

> **Before you start, you need:**
>
> - An Omnipod 5 whose data is uploading to **Glooko** (the Omnipod 5 app already syncing your Pod to Glooko)
> - Your **Glooko** email and password
> - GlycemicGPT running and you signed in

---

## A note on how this connection works

Glooko doesn't offer an official way for other apps to connect. So GlycemicGPT connects by **signing in to Glooko the same way the website does, using your own credentials** — there's no official Glooko integration behind it.

Because this isn't something Glooko officially supports, connecting Omnipod asks you to **check a box** confirming you understand that. You're connecting **your own account, by choice.** GlycemicGPT only ever *reads* your data — it never uploads anything back to Glooko. We're not aware of Glooko taking action against accounts for this, but since it's unofficial we'd rather you know how it works than be surprised.

---

## Continuous sync

This keeps GlycemicGPT updated automatically. After you connect, a background job pulls your recent data from Glooko on a schedule — no phone, no app, nothing to re-run day to day.

### What it pulls

- **Basal** (scheduled rate)
- **Boluses** (insulin delivered, with insulin-on-board at the time of the bolus)
- **Pod changes and events** (pod activation, reservoir/cannula changes, suspends/resumes)
- **Smart-pen doses** (NovoPen 6 / Echo Plus boluses and manual insulin logs — see [Smart insulin pens](#smart-insulin-pens-novopen-6--echo-plus) below)
- **Sensor glucose** (your CGM trace) — **when available.** Omnipod 5 only streams integrated CGM to Glooko on some setups, so this isn't guaranteed. The card tells you honestly whether CGM data was found in your account.

### Setting it up

In your GlycemicGPT dashboard:

1. Go to **Settings → Integrations → Cloud Sync** and find **Omnipod / Glooko**.
2. Enter your **Glooko email** and **password**, and pick your **region** (United States or Europe / International).
3. Check the box confirming you understand this is an **unofficial connection** (see above).
4. Click **Connect Glooko**. GlycemicGPT signs in to confirm your credentials work, then stores them encrypted and starts syncing.

Once connected, the card shows whether sensor glucose is available, your last sync time, and how many readings have synced so far.

### How often does it sync?

Every **30 minutes** by default. You can change the interval (15 minutes to 24 hours) in the Omnipod / Glooko section. Syncing more often than Glooko's own cloud updates doesn't get you fresher data.

### If the connection breaks

If your Glooko password changes or the login otherwise stops working, the connection shows as **disconnected** and prompts you to reconnect. **Disconnect and reconnect** with your current Glooko password to resume syncing.

---

## One-time import (historical backfill)

Use this to pull your history once — for example, to backfill the weeks or months before you set up continuous sync.

### How it works

1. In **Settings → Integrations → Cloud Sync → Omnipod / Glooko**, after you've connected, click **Import history (one-time)**.
2. GlycemicGPT walks back through your Glooko history and brings it in. This can take a minute.

The import fills in the **past** without disturbing your ongoing continuous sync, and it's **safe to run again** — GlycemicGPT de-duplicates readings, so importing a range you already have just does nothing.

---

## Smart insulin pens (NovoPen 6 / Echo Plus)

You don't need a pump for this connection to be useful. If you're on injections with a **Novo Nordisk NovoPen 6 or NovoPen Echo Plus**, the same Glooko connection brings your **pen doses** into GlycemicGPT:

1. Install the free **Glooko app** on your phone (iOS or Android) and sign in.
2. After injecting, hold the pen's display against your phone's NFC reader and sync (Home → **Sync** → **Smart Pens** the first time). The pen's memory holds a long dose history, so even an occasional scan keeps GlycemicGPT complete.
3. Connect Glooko in GlycemicGPT as described above — pen doses flow in on the same schedule as pump data, and the one-time import backfills your pen history.

What lands in GlycemicGPT:

- **Rapid-acting (bolus) pen doses** read from the pen, plus insulin doses you typed into the Glooko app by hand (flagged as manually entered).
- **Priming shots are excluded.** The pen records every actuation, including the 1–2 unit air shots used to prime the needle. Glooko flags these and GlycemicGPT skips them, so they never inflate your dose totals or AI analysis.
- **Long-acting (basal) pen doses are not imported yet.** They don't fit the pump-style basal-rate model, so rather than show them misleadingly, they're skipped for now — support is tracked as a follow-up.

> **Heads-up on dose edits:** if you delete or correct a dose in Glooko, the deletion is honored on the next sync for records not yet imported, but doses already stored in GlycemicGPT are keyed by Glooko's stable record ID and won't be retroactively removed. This matches how the pump streams behave.

---

## Privacy

- For continuous sync, your stored Glooko **email and password** are **encrypted at rest** (using your `SECRET_KEY`) and are never shown back to you or returned in any response.
- Data flows in one direction only: from Glooko's cloud into GlycemicGPT. GlycemicGPT never pushes anything back to Glooko.
- See [Privacy](../concepts/privacy.md) for the full picture.

## Stability of the Glooko path

Honest disclosure: Glooko does not publish a developer API, and its web sign-in is marked experimental upstream. GlycemicGPT's Glooko integration is a clean-room implementation built from publicly documented protocol behavior, crediting prior community reverse-engineering work — [nightscout-connect](https://github.com/nightscout/nightscout-connect) and the [glooko2nightscout-bridge](https://github.com/jpollock/glooko2nightscout-bridge) (both AGPL-3.0, studied for protocol only, never copied) and the [Tidepool data model](https://github.com/tidepool-org/TidepoolApi) (BSD-2-Clause) for pod-change modeling. These are credited in `THIRD_PARTY_LICENSES.md`.

What this means in practice:

- **Glooko can break it.** Sign-in flows and data shapes can change without notice; when they do, expect a lag of days to weeks for a fix.
- **CGM availability depends on your setup.** Pump data syncs reliably; sensor glucose only appears if your Omnipod streams integrated CGM to Glooko.
- **It's an unofficial connection.** Glooko doesn't offer an official integration, so this works by signing in with your credentials — see the note above.

## When the integration breaks

- **Connection shows disconnected:** your Glooko sign-in expired or your password changed. Disconnect and reconnect with your current password.
- **Import finds nothing / no CGM:** sign in at the Glooko website to confirm your Pod is actually uploading, and that the account has data for the period you expect.

## Still stuck?

If the connection says active but data isn't appearing, see [BG isn't updating](../troubleshooting/bg-not-updating.md).
