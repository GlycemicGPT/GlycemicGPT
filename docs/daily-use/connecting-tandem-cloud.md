---
title: Connecting Your Tandem Pump (Cloud)
description: How GlycemicGPT integrates with the Tandem t:connect cloud, in both directions.
---

Tandem pumps can flow data into GlycemicGPT through two paths: cloud (this page) or Bluetooth via the mobile app. Most users will end up using both. This page covers the cloud path.

> **Cloud vs Bluetooth, what's the difference?**
>
> | Path | What you get | When it updates |
> |---|---|---|
> | Cloud (this page) | Pump history fetched from Tandem's servers | Every ~60 minutes |
> | Bluetooth via [mobile app](../mobile/install.md) | Real-time IoB, basal, BG, battery, reservoir | Every few minutes |
>
> The cloud path doesn't require the mobile app. The Bluetooth path requires the mobile app. Most users want the Bluetooth path for the live dashboard and the cloud path as a backstop / for historical fill-in.

> **Before you start, you need:**
>
> - A Tandem pump (t:slim X2 or Mobi -- see Mobi caveat below) with the official t:connect mobile / desktop app already syncing your pump to the Tandem cloud
> - Your Tandem account email and password
> - GlycemicGPT running and you signed in

> **Mobi caveat:** the Mobi shares most of the t:slim X2 protocol and the GlycemicGPT cloud integration is expected to work with Mobi, but the project lead does not own a Mobi for continuous verification. Mobi field reports welcome via [Discord](https://discord.gg/QbyhCQKDBs).

## Two directions of integration

GlycemicGPT's Tandem cloud integration is **bidirectional** -- which is more than what most people expect.

| Direction | What it does | Why it exists |
|---|---|---|
| **Pull from Tandem → GlycemicGPT** (default, primary) | Fetches your pump history from Tandem's cloud (boluses, basal, Control-IQ corrections, settings) on a 60-min schedule | Gives GlycemicGPT historical pump data even if you don't use the mobile app |
| **Push from GlycemicGPT → Tandem** (optional, off by default) | Uploads BLE-captured pump data from GlycemicGPT *back* to Tandem's cloud, so your endocrinologist's t:connect portal stays current | Keeps your clinician's view in sync if you use GlycemicGPT instead of (or in addition to) the official t:connect mobile app |

Both directions use your t:connect credentials. They are configured separately -- you can have one without the other.

## What "t:connect cloud" is

t:connect is Tandem's cloud service. The official t:connect mobile app or desktop uploader syncs your pump's history (boluses, basal changes, alarms, settings) to Tandem's servers periodically -- typically every 60 minutes from the mobile app. Once your data is in the t:connect cloud, GlycemicGPT can pull it. And -- in the upload direction -- GlycemicGPT can push BLE-captured data back to those same servers.

If you've never used t:connect before, set it up first:

- iOS: install the **t:connect mobile** app from the App Store
- Android: install the **t:connect mobile** app from the Play Store
- Web: sign in at [tconnect.tandemdiabetes.com](https://tconnect.tandemdiabetes.com)

Sign in, pair your pump, and let it sync at least once. After you see your pump data in the t:connect web portal, you're ready.

## Setting up the pull (Tandem → GlycemicGPT)

This is what most users want. It's the default direction.

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

Watch your dashboard -- you should start seeing pump history populate (boluses, basal changes, Control-IQ corrections).

### How often does it sync?

Default is every 60 minutes, matching the speed at which the t:connect app uploads to the cloud. Checking more often doesn't help -- if t:connect hasn't synced new data yet, GlycemicGPT can't see it.

For real-time data (IoB, basal, glucose every few minutes), use the Bluetooth path instead via the [mobile app](../mobile/install.md).

### What does GlycemicGPT pull from t:connect?

- Bolus history (when, how much, manual or automatic, Control-IQ corrections flagged separately)
- Basal rate changes
- Pump alerts and alarms
- Pump settings (carb ratios, correction factors, target ranges)
- Pump device metadata (serial number, model)

It does **not** read CGM data via t:connect for the live dashboard -- the cloud path is too slow for live glucose. CGM data on the dashboard comes from the [Dexcom integration](./connecting-dexcom.md) or the mobile app's BLE stream.

## Setting up the push (GlycemicGPT → Tandem) -- optional

This direction is **off by default**. You only want this if you use GlycemicGPT's mobile app as your primary pump-Bluetooth client *and* you want your endocrinologist's t:connect portal to stay current. If you still use the official t:connect mobile app, you don't need this -- it'll keep uploading on its own.

### How it works

The mobile app captures raw pump events over Bluetooth and stores them in GlycemicGPT. The backend then takes those raw events and uploads them to Tandem's cloud using the same upload endpoint that the official t:connect mobile app uses, with a request signature derived from a key extracted by reverse-engineering the official app. From Tandem's perspective, the upload looks like the t:connect mobile app -- just running on your GlycemicGPT server instead of your phone.

This is the same path the [tconnectsync](https://github.com/jwoglom/tconnectsync) library and tools like the now-defunct [tconnectpatcher](https://github.com/jamoocha/tconnectpatcher) have implemented over the years.

### Configure the upload

1. **Settings → Integrations → Tandem → Cloud Upload**
2. Toggle the upload on
3. Pick an upload interval (default: 15 minutes)
4. Save

The pull direction must be configured first (the upload reuses the same credentials). The upload runs in the background; there's nothing else to do.

### Why it's off by default

- Most users either (a) keep using the official Tandem app and don't need the upload, or (b) explicitly do not want their data going back to Tandem's cloud beyond what their pump itself uploads.
- The upload depends on impersonating the official Tandem mobile app, which is a more invasive integration shape than the pull direction. Off-by-default lets you opt in deliberately.

### Future: pump-report-only configuration

A future direction (not implemented today) is to allow users who *don't* want a direct pump integration at all to instead configure GlycemicGPT to ingest the pump reports they manually generate from t:connect (PDF / CSV exports). This would let GlycemicGPT analyze pump history for users who want to keep their pump data flow entirely separate from a real-time integration. Track this in [ROADMAP.md](../../ROADMAP.md).

## Privacy

- Your Tandem credentials are encrypted on the platform
- Pump data flows in whichever direction(s) you've configured -- pull-only by default
- The upload direction sends data only to Tandem's cloud (the same destination as the official t:connect app); no third-party data sharing
- GlycemicGPT does not share your pump data with anyone (see [Privacy](../concepts/privacy.md))

## When the integration breaks

If your Tandem account password changes, the platform's credentials become invalid. The integration will eventually show as **Disconnected**. Update the password in **Settings → Integrations → Tandem**. (Both directions break at the same time, since they share credentials.)

If you see Tandem-side errors in the platform logs, sign in at [tconnect.tandemdiabetes.com](https://tconnect.tandemdiabetes.com) to confirm your account is in good standing. If t:connect itself is down or your account is locked, GlycemicGPT can only show what t:connect has.

## Stability of the t:connect cloud path

Honest disclosure: GlycemicGPT's t:connect integration sits on top of an unofficial-from-our-side path in **both directions**. Tandem does not publish a developer API. The pull direction reuses the [tconnectsync](https://github.com/jwoglom/tconnectsync) library; the push direction goes through endpoints and request shapes derived from reverse-engineering the official t:connect mobile app.

What this means in practice:

- **Tandem can break it.** They've broken similar community projects before -- [tconnectpatcher](https://github.com/jamoocha/tconnectpatcher), an earlier reverse-engineering effort, died in 2022 when its targeted t:connect version (v1.2 from 2020) got rotated out. Auth flows, endpoints, and response shapes change without notice.
- **When it breaks, fixes take time.** The maintainers of the underlying libraries are responsive but unpaid; expect days to weeks for a fix when Tandem rotates something major. The push direction is more fragile than the pull direction because it impersonates the mobile app at a deeper level.
- **The Bluetooth path through the mobile app is more stable than either cloud direction** because it talks to the pump directly, not to Tandem's cloud. If you're using GlycemicGPT primarily for live data, treat the cloud integration as a backup / history-fill-in path and the Bluetooth path as primary.

If you depend on the cloud path for caregiver alerts or anything time-sensitive, plan for the integration to occasionally lag by a day or two during a Tandem-side rotation.

## Still stuck?

If the integration says **Connected** but pump data isn't appearing, see the troubleshooting section in [BG isn't updating](../troubleshooting/bg-not-updating.md).

For real-time pump data (IoB updating every few minutes, glucose if your pump streams it), set up the [mobile app](../mobile/install.md) and pair your pump over Bluetooth -- that's the path that gives you live data.
