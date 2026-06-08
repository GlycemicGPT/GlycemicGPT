---
title: Connecting Your Tandem Pump (Cloud)
description: How GlycemicGPT integrates with the Tandem t:connect cloud.
---

GlycemicGPT can pull your pump's history from the Tandem t:connect cloud on a schedule. Boluses, basal changes, Control-IQ corrections, and pump settings flow into GlycemicGPT so the dashboard and AI analysis have the same data your endocrinologist sees in t:connect.

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
> - A Tandem t:slim X2 with the official t:connect mobile or desktop app already syncing your pump to the Tandem cloud
> - Your Tandem account email and password
> - GlycemicGPT running and you signed in

## A note on the upload direction

GlycemicGPT used to also offer the reverse direction -- pushing BLE-captured pump events from your GlycemicGPT instance *back* to the t:connect cloud so an endocrinologist's portal would stay current. **That feature was removed.** Pushing data into a clinical-record system used by endocrinologists for dosing decisions, while impersonating Tandem's official mobile app, was a regulatory and patient-safety risk we weren't equipped to ship responsibly as an open-source project without medical-device certification.

If your goal is to make sure your endo sees pump data in their t:connect portal, the safer paths are:

- Keep the official Tandem mobile app installed and paired to your pump (it'll upload to t:connect on its own).
- Or export a PDF/CSV report from GlycemicGPT and share that with your endocrinologist directly.

The rest of this page is about the **pull** direction (Tandem cloud → GlycemicGPT), which remains supported.

## What "t:connect cloud" is

t:connect is Tandem's cloud service. The official t:connect mobile app or desktop uploader syncs your pump's history (boluses, basal changes, alarms, settings) to Tandem's servers periodically -- typically every 60 minutes from the mobile app. Once your data is in the t:connect cloud, GlycemicGPT can pull it.

If you've never used t:connect before, set it up first:

- iOS: install the **t:connect mobile** app from the App Store
- Android: install the **t:connect mobile** app from the Play Store
- Web: sign in at [tconnect.tandemdiabetes.com](https://tconnect.tandemdiabetes.com)

Sign in, pair your pump, and let it sync at least once. After you see your pump data in the t:connect web portal, you're ready.

## Setting up the pull (Tandem → GlycemicGPT)

### 1. Configure the integration in GlycemicGPT

In your GlycemicGPT dashboard:

1. Go to **Settings → Integrations**
2. Find **Tandem (t:connect)** and click **Connect**
3. Paste your **t:connect email**
4. Paste your **t:connect password**
5. Pick the **country** your t:connect account is registered in (see below)
6. Click **Save**

The platform stores credentials encrypted (using your `SECRET_KEY` from `.env`).

### Picking the right country

Tandem operates two cloud backends — a US cluster and an EU cluster — and routes each country to one of them via a per-country config endpoint. The picker shows every country Tandem currently provisions, grouped by cluster for readability.

| Cluster | Countries Tandem provisions |
|---|---|
| **US cloud** | United States, Canada, Mexico |
| **EU cloud** | United Kingdom, Ireland, EEA (DE, FR, IT, ES, NL, BE, SE, NO, FI, DK, PT, LU, CH, AT, GR, PL, CZ, SK, HU, SI, HR, RO, BG, IS, EE, LV, LT, MT), Australia, New Zealand, Israel, South Africa, plus RU, UA, RS, BA, AL, ME, MK |

If your country isn't in the picker, Tandem hasn't published a config for it — t:slim X2 isn't sold there commercially today (Japan, Korea, India, Brazil, etc. all fall into this bucket).

Picking the wrong country will make the sync fail because GlycemicGPT will authenticate against the wrong cluster. The integration row will show an error and you can simply reconnect with the right country.

> **Existing users:** If you connected Tandem before the country picker existed (when only "US" / "EU" were stored), you'll see a status of "needs country re-select." Re-connect with your country selected to clear it.

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

## Privacy

- Your Tandem credentials are encrypted on the platform
- Pump data flows in only one direction: from Tandem's cloud into GlycemicGPT (the push direction was removed)
- GlycemicGPT does not share your pump data with anyone (see [Privacy](../concepts/privacy.md))

## When the integration breaks

If your Tandem account password changes, the platform's credentials become invalid. The integration will eventually show as **Disconnected**. Update the password in **Settings → Integrations → Tandem**.

If you see Tandem-side errors in the platform logs, sign in at [tconnect.tandemdiabetes.com](https://tconnect.tandemdiabetes.com) to confirm your account is in good standing. If t:connect itself is down or your account is locked, GlycemicGPT can only show what t:connect has.

## Stability of the t:connect cloud path

Honest disclosure: GlycemicGPT's t:connect integration sits on top of an unofficial-from-our-side path. Tandem does not publish a developer API. The pull direction reuses the [tconnectsync](https://github.com/jwoglom/tconnectsync) library.

What this means in practice:

- **Tandem can break it.** They've broken similar community projects before -- [tconnectpatcher](https://github.com/jamoocha/tconnectpatcher), an earlier reverse-engineering effort, died in 2022 when its targeted t:connect version (v1.2 from 2020) got rotated out. Auth flows, endpoints, and response shapes change without notice.
- **When it breaks, fixes take time.** The maintainers of the underlying library are responsive but unpaid; expect days to weeks for a fix when Tandem rotates something major.
- **The Bluetooth path through the mobile app is more stable than the cloud path** because it talks to the pump directly. If you're using GlycemicGPT primarily for live data, treat the cloud integration as a backup / history-fill-in path and the Bluetooth path as primary.

If you depend on the cloud path for caregiver alerts or anything time-sensitive, plan for the integration to occasionally lag by a day or two during a Tandem-side rotation.

## Still stuck?

If the integration says **Connected** but pump data isn't appearing, see the troubleshooting section in [BG isn't updating](../troubleshooting/bg-not-updating.md).

For real-time pump data (IoB updating every few minutes, glucose if your pump streams it), set up the [mobile app](../mobile/install.md) and pair your pump over Bluetooth -- that's the path that gives you live data.
