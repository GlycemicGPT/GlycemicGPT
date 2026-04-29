---
title: Connecting Your Dexcom CGM
description: Hook GlycemicGPT up to your Dexcom G7 cloud account.
---

GlycemicGPT pulls Dexcom G7 data from the Dexcom Cloud (Dexcom Share) -- you don't need to do anything on your phone for this; the platform polls Dexcom directly on a schedule.

> **Before you start, you need:**
>
> - A Dexcom G7 sensor + transmitter, actively transmitting data
> - A Dexcom Share account (you set this up in the official Dexcom G7 app)
> - The platform running and you signed in to your dashboard

## What "Dexcom Share" is and why you need it

Dexcom Share is the cloud component of the Dexcom system. Your CGM transmits to your phone over Bluetooth, the Dexcom app uploads to Dexcom's cloud, and other apps (with your permission) can read your data from the cloud. GlycemicGPT is "another app" in this sense.

If you're already using Dexcom Follow / Clarity or another diabetes app that reads from Dexcom, you've already got a Share account. If not, set it up in the Dexcom G7 app under **Settings → Share** -- it's free.

## Steps

### 1. Confirm Dexcom Share is enabled

In the official Dexcom G7 app on your phone:

1. Open **Settings → Share**
2. Confirm you have at least one followers entry (or that Share is on -- the wording varies by region and app version)
3. Confirm your Dexcom account is in good standing -- if you can sign in to [dexcom.com](https://www.dexcom.com) and see your data, you're set

### 2. Configure the integration in GlycemicGPT

In your GlycemicGPT dashboard:

1. Go to **Settings → Integrations**
2. Find **Dexcom** and click **Connect**
3. Paste your **Dexcom Share email** (the email associated with your Dexcom account)
4. Paste your **Dexcom Share password**
5. Pick your **server region** (US / OUS for outside-US -- if you're in the US, pick US)
6. Click **Save**

GlycemicGPT stores your credentials encrypted on the platform and uses them to poll Dexcom Cloud.

### 3. Wait for the first sync

The integration polls Dexcom on a schedule (typically every 5-10 minutes). The first poll happens within a minute of saving credentials. Watch your dashboard -- glucose readings should start appearing.

If after 5-10 minutes you don't see glucose data, see [BG isn't updating](../troubleshooting/bg-not-updating.md).

## How often does it sync?

The polling interval is configurable -- typical values are 5 to 10 minutes. Faster polling means fresher data on the dashboard but slightly higher load on Dexcom's API; slower polling is fine for most users.

You can change this in **Settings → Integrations → Dexcom → Polling interval**.

## What happens if my Dexcom Share password changes?

The platform's stored credentials become invalid. The dashboard will eventually show the integration as **Disconnected**. Update your password in **Settings → Integrations → Dexcom**.

## Privacy

- Your Dexcom credentials are encrypted on the platform using your `SECRET_KEY` (set in `.env`)
- Glucose readings live on the platform's database -- not on Dexcom's servers any longer than they already were
- GlycemicGPT does not send your data anywhere else (see [Privacy](../concepts/privacy.md))

## Why doesn't my Dexcom G6 / G5 / Libre work?

Today the platform supports Dexcom G7 only. Additional CGM support (Libre, Medtronic Guardian, possibly G6) is on the roadmap -- see [ROADMAP.md](../../ROADMAP.md) §Phase 2.

If you have an unsupported CGM but use a platform like Nightscout, integration with Nightscout is also planned -- you'd connect Nightscout to your CGM and GlycemicGPT to Nightscout. Same roadmap phase.

## Still stuck?

If the integration says **Connected** but glucose isn't updating, see [BG isn't updating -- Dexcom path](../troubleshooting/bg-not-updating.md#dexcom-g7-path).

If the integration won't accept your credentials, sign in at [dexcom.com](https://www.dexcom.com) directly with the same email and password to confirm they work. If the Dexcom website rejects them, your account itself has an issue -- contact Dexcom support.
