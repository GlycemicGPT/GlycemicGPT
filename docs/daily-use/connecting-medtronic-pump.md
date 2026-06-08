---
title: Pairing Your Medtronic Pump over Bluetooth (Beta)
description: Pair a Medtronic MiniMed 700-series pump (680G / 770G / 780G) directly to the GlycemicGPT mobile app over Bluetooth — no cloud account, read-only.
---

The GlycemicGPT mobile app can connect to a **Medtronic MiniMed 700-series pump directly over Bluetooth** — no Medtronic account, no cloud, no browser step. Your phone pairs with the pump the same way a CGM display or accessory would, and reads sensor glucose, insulin-on-board, basal, bolus history, reservoir, and battery straight off the pump.

This is **read-only.** GlycemicGPT never sends anything to the pump — no boluses, no basal changes, no setting changes. It only reads.

> **Beta.** On-device Bluetooth pairing is new and still being validated against live pumps. Treat the data as beta and sanity-check important values against the pump itself. If something looks wrong, [open an issue](https://github.com/GlycemicGPT/GlycemicGPT/issues/new/choose).

## Bluetooth (this page) vs CareLink cloud sync — which do I want?

There are **two unrelated ways** to get Medtronic data into GlycemicGPT. They don't depend on each other; pick whichever fits.

| | **Pair over Bluetooth** (this page) | **[CareLink cloud sync](./connecting-medtronic.md)** |
|---|---|---|
| How | Phone talks to the pump directly over BLE | GlycemicGPT pulls from Medtronic's cloud |
| Needs | The pump in Bluetooth range of your phone | A CareLink account + browser sign-in |
| App | GlycemicGPT **mobile app** | Works with the web dashboard |
| Account | None | CareLink login (captcha in your browser) |
| Freshness | As fast as the pump reports | Whatever the cloud has (delayed) |

Use **Bluetooth** if you want the freshest data and your phone is usually near the pump. Use **CareLink cloud sync** if you'd rather not pair the pump to your phone, or you also want history that's already in Medtronic's cloud. You *can* run both, but most people pick one.

## Before you start

- A Medtronic **MiniMed 680G, 770G, or 780G** pump (the 700-series). Older MiniMed pumps are not supported.
- The **GlycemicGPT mobile app** installed and signed in.
- Bluetooth turned on, and the pump within a few feet of the phone.

> **Remove the pump from the official Medtronic app first.** A MiniMed pump pairs with **only one phone at a time.** If the pump is currently paired to Medtronic's own app (MiniMed Mobile) — or any other phone — it won't pair with GlycemicGPT until you remove it there. The app shows this same reminder on the pairing screen.

## How pairing works

Unlike a Tandem pump (where your phone scans for the pump), a MiniMed pump is the one that goes looking. So pairing is **advertise-and-wait**: GlycemicGPT makes your phone discoverable as a Bluetooth accessory named **"Mobile 000001"**, and then you tell the pump to connect to it from the pump's own menu. Your phone waits; the pump initiates.

## Pairing steps

1. In the GlycemicGPT mobile app, go to the pump settings and choose **Medtronic** as your pump.
2. Open **Pump Pairing**. You'll see a **"Before you start"** note about removing the pump from the manufacturer's app first.
3. Tap **Start Pairing**. Your phone becomes discoverable as **"Mobile 000001"** and shows **"Waiting for your pump."**
4. On the **pump**, open the Bluetooth pairing menu (**Add / Pair new device**) and select **"Mobile 000001."**
5. Confirm the pairing on the pump if it prompts you. The app moves from *waiting* → *connecting* → connected, and your data begins to appear on the dashboard.

Once paired, the pump is remembered — GlycemicGPT reconnects on its own when the pump is back in range; you don't repeat this flow.

## What it reads

- **Sensor glucose** (your CGM trace) — drives the dashboard, time-in-range, and alerts
- **Insulin-on-board (IoB)**
- **Basal rate** (the active rate)
- **Bolus history**
- **Reservoir** level and **pump battery**

> Basal is shown as the active rate the pump reports; SmartGuard auto-basal micro-boluses are not yet fully attributed, and IoB is read straight off the pump as it exposes it. These are documented limitations of the on-device read path while the data mapping is validated against live pumps.

## If pairing doesn't complete

The pairing screen tells you what happened and offers **Try Again**:

- **"No pump has connected yet."** Nothing selected your phone. Make sure the pump isn't still paired to the manufacturer's app, that Bluetooth is on, and that you picked **"Mobile 000001"** in the pump's pairing menu.
- **"This phone can't act as a Bluetooth accessory."** Some phones can't advertise as a BLE peripheral, which this pairing needs. Try a different phone.
- **"Couldn't start Bluetooth advertising."** Close other Bluetooth apps and try again.
- **"The secure handshake timed out"** / **"the pump rejected the secure handshake."** The pump connected but the encrypted session didn't establish. Try again; keep the pump close.

## Privacy

- Pairing is **direct, phone-to-pump.** No Medtronic account is involved and nothing leaves your phone to a third party as part of pairing.
- The connection is **read-only** — data flows from the pump into GlycemicGPT only.
- See [Privacy](../concepts/privacy.md) for the full picture.

## Still stuck?

If the pump shows as connected but data isn't appearing, see [BG isn't updating](../troubleshooting/bg-not-updating.md), or ask on [Discord](https://discord.gg/QbyhCQKDBs) with your phone model and pump model.
