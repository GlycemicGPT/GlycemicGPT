---
title: Connecting Your Tandem Pump (Cloud)
description: Sync Tandem t:slim X2 / Mobi pump data via the t:connect cloud.
---

Tandem pumps can flow data into GlycemicGPT through two paths: cloud (this page) or Bluetooth via the mobile app. Most users will end up using both. This page covers the cloud path.

> **Cloud vs Bluetooth, what's the difference?**
>
> | Path | What you get | When it updates |
> |---|---|---|
> | Cloud (this page) | Pump history, boluses, basal changes | Every ~60 minutes (Tandem's cloud sync interval) |
> | Bluetooth via [mobile app](../mobile/install.md) | Real-time IoB, basal, BG, battery, reservoir | Every few minutes |
>
> The cloud path doesn't require the mobile app. The Bluetooth path requires the mobile app. Most users want the Bluetooth path for the live dashboard and the cloud path as a backstop / for historical fill-in.

> **Before you start, you need:**
>
> - A Tandem pump (t:slim X2 or Mobi) with the official t:connect mobile / desktop app already syncing your pump to the Tandem cloud
> - Your Tandem account email and password
> - GlycemicGPT running and you signed in

## What "t:connect cloud" is

t:connect is Tandem's cloud service. The official t:connect mobile app or desktop uploader syncs your pump's history (boluses, basal changes, alarms, settings) to Tandem's servers periodically -- typically every 60 minutes from the mobile app. Once your data is in the t:connect cloud, GlycemicGPT can pull it.

If you've never used t:connect before, set it up first:

- iOS: install the **t:connect mobile** app from the App Store
- Android: install the **t:connect mobile** app from the Play Store
- Web: sign in at [tconnect.tandemdiabetes.com](https://tconnect.tandemdiabetes.com)

Sign in, pair your pump, and let it sync at least once. After you see your pump data in the t:connect web portal, you're ready.

## Steps

### 1. Configure the integration in GlycemicGPT

In your GlycemicGPT dashboard:

1. Go to **Settings → Integrations**
2. Find **Tandem (t:connect)** and click **Connect**
3. Paste your **t:connect email**
4. Paste your **t:connect password**
5. Click **Save**

The platform stores credentials encrypted (using your `SECRET_KEY` from `.env`).

### 2. Wait for the first sync

GlycemicGPT pulls from t:connect on a schedule. The first pull happens within a few minutes; subsequent pulls follow the configured interval (default: every 60 minutes, matching t:connect's own sync rate).

Watch your dashboard -- you should start seeing pump history populate (boluses, basal changes).

## How often does it sync?

Default is every 60 minutes, matching the speed at which the t:connect app uploads to the cloud. Checking more often doesn't help -- if t:connect hasn't synced new data yet, GlycemicGPT can't see it.

For real-time data (IoB, basal, glucose every few minutes), use the Bluetooth path instead via the [mobile app](../mobile/install.md).

## What does GlycemicGPT pull from t:connect?

- Bolus history (when, how much, manual or automatic)
- Basal rate changes
- Pump alerts and alarms
- Pump settings (carb ratios, correction factors, target ranges)

It does **not** read CGM data via t:connect for the live dashboard -- the cloud path is too slow for live glucose. CGM data on the dashboard comes from the [Dexcom integration](./connecting-dexcom.md) or the mobile app's BLE stream.

## Privacy

- Your Tandem credentials are encrypted on the platform
- Pump data flows from Tandem's cloud to your GlycemicGPT instance and is stored there
- GlycemicGPT does not share your pump data with anyone (see [Privacy](../concepts/privacy.md))

## When the integration breaks

If your Tandem account password changes, the platform's credentials become invalid. The integration will eventually show as **Disconnected**. Update the password in **Settings → Integrations → Tandem**.

If you see Tandem-side errors in the platform logs, sign in at [tconnect.tandemdiabetes.com](https://tconnect.tandemdiabetes.com) to confirm your account is in good standing. If t:connect itself is down or your account is locked, GlycemicGPT can only show what t:connect has.

## Still stuck?

If the integration says **Connected** but pump data isn't appearing, see the troubleshooting section in [BG isn't updating](../troubleshooting/bg-not-updating.md).

For real-time pump data (IoB updating every few minutes, glucose if your pump streams it), set up the [mobile app](../mobile/install.md) and pair your pump over Bluetooth -- that's the path that gives you live data.
