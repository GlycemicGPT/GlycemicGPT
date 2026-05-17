---
title: Connecting Your Dexcom CGM
description: Hook GlycemicGPT up to your Dexcom account so glucose flows into the dashboard automatically.
---

GlycemicGPT pulls Dexcom data from Dexcom's cloud using your normal Dexcom account credentials. You don't need to do anything on your phone for this; the platform checks Dexcom for new data directly on a schedule.

> **If you're already running Nightscout:** you can connect your Nightscout instance directly instead of (or alongside) Dexcom -- GlycemicGPT will read CGM entries, treatments, and your profile from your Nightscout site. See [Integrations → Nightscout](./integrations.md#nightscout) for the guided setup. If you connect both Dexcom and Nightscout, the platform will pull from both; pick one if you want to avoid the duplicate Dexcom-cloud poll.

> **Before you start, you need:**
>
> - A Dexcom CGM (sensor + transmitter) actively transmitting data
> - Your **Dexcom account** -- the same email and password you use to sign in at [dexcom.com](https://www.dexcom.com), the Dexcom mobile app, or Dexcom Clarity. You don't need a separate "Share" account.
> - The platform running and you signed in to your dashboard

## How this works behind the scenes

Your CGM transmits to your phone over Bluetooth, the Dexcom mobile app uploads to Dexcom's cloud, and GlycemicGPT reads from Dexcom's cloud using your account credentials. You don't need to enable any special "Share" or "Follow" setting -- as long as your CGM is uploading to Dexcom (which it does automatically when you have the Dexcom mobile app installed and signed in), GlycemicGPT can pull the data.

## Steps

### 1. Confirm your CGM is uploading to Dexcom

If you can sign in at [dexcom.com](https://www.dexcom.com) (or open Dexcom Clarity) and see recent glucose readings, your CGM is uploading and you're ready. If you can't see recent data there, the issue is upstream of GlycemicGPT (sensor, transmitter, or your phone's Dexcom app) -- fix that first; GlycemicGPT can only sync what Dexcom has.

### 2. Configure the integration in GlycemicGPT

In your GlycemicGPT dashboard:

1. Go to **Settings → Integrations**
2. Find **Dexcom** and click **Connect**
3. Paste the **email address** for your Dexcom account
4. Paste the **password** for your Dexcom account
5. Pick the **region** that matches your Dexcom account (see below)
6. Click **Save**

GlycemicGPT stores your credentials encrypted on the platform and uses them to check Dexcom for new data on your behalf. The platform never sends your password anywhere except to Dexcom itself, and you can delete the credentials at any time by disconnecting the integration.

### Picking the right region

Dexcom Share is regional. There are three Share endpoints; pick the one that matches where your Dexcom account is registered:

| Region | Use this when your account is from |
|---|---|
| **United States** | The United States |
| **Outside US** | EU/EEA, UK, Canada, Australia, New Zealand, South Africa, LATAM, Middle East, or anywhere not US/Japan |
| **Japan & Asia-Pacific** | Japan or other Asia-Pacific countries that use Dexcom's APAC service |

A region mismatch and a wrong password look identical from Dexcom's side — both come back as "invalid credentials." If your password is correct on the Dexcom website but GlycemicGPT rejects it, the region picker is the first thing to check.

> Dexcom locks the account after a small number of failed login attempts per region. Don't burn through retries — confirm your region first.

### If login fails: enable Dexcom Share

GlycemicGPT reads from Dexcom's Share endpoint (the same API the Dexcom Follow feature uses). On most accounts Share is already active because the Dexcom mobile app turns it on automatically the first time data flows. If login fails despite the right region:

1. Open the Dexcom G6/G7 mobile app
2. Go to **Share** in the menu
3. Make sure Share is **on**
4. Invite at least one follower (your own second email works) — Dexcom only fully activates the Share API after the first follower invite exists

### 3. Wait for the first sync

The integration checks Dexcom for new data on a schedule (typically every 5-10 minutes). The first check happens within a minute of saving credentials. Watch your dashboard -- glucose readings should start appearing.

If after 5-10 minutes you don't see glucose data, see [BG isn't updating](../troubleshooting/bg-not-updating.md).

## How often does it sync?

The platform checks Dexcom on a fixed default interval (5 minutes). The polling interval is configured server-side via the `DEXCOM_SYNC_INTERVAL_MINUTES` environment variable today; a per-user UI control to change this from the dashboard is on the roadmap. For most users 5 minutes matches Dexcom's own update cadence and there's no reason to change it.

## Does this affect the regular Dexcom app on my phone?

No. GlycemicGPT reads from Dexcom's servers using your account credentials in exactly the same way the Dexcom mobile app, Dexcom Clarity, and the Dexcom website all do. Your phone keeps streaming readings to Dexcom; Dexcom's official alerts on your phone keep firing as before; Clarity, Share, and Follow all keep working normally. GlycemicGPT is an additional, parallel reader of the same cloud data -- it doesn't replace or interfere with anything.

## What happens if my Dexcom password changes?

The platform's stored credentials become invalid. The dashboard will eventually show the integration as **Disconnected**. Update your password in **Settings → Integrations → Dexcom**.

## Privacy

- Your Dexcom credentials are encrypted on the platform using your `SECRET_KEY` (set in `.env`)
- Glucose readings live on your platform's database
- GlycemicGPT does not send your data anywhere else (see [Privacy](../concepts/privacy.md))

## Why does this use my password instead of OAuth?

Dexcom does have an [official developer API](https://developer.dexcom.com/) that uses OAuth, which would be the obvious privacy-preferring choice. The reasons GlycemicGPT does not use it today:

- **Approval-gated.** Dexcom's developer API requires per-application approval. The library this project uses ([pydexcom](https://github.com/gagebenne/pydexcom)) bypasses that approval gate by using the same Share-API path the official Dexcom Follow / Clarity apps use, with the user's own credentials.
- **Heavily rate-limited.** The official developer API caps polling at intervals that don't match what live monitoring needs.
- **Same path the rest of the OSS world uses.** Nightscout's `dexcom-share` plugin, Sugarmate, Spike, and the broader diabetes-OSS community all rely on the same Share-API path. We're not introducing a new pattern here -- we're using the established one.

The trade-off is that GlycemicGPT stores your Dexcom *password* (encrypted, but reversibly with your `SECRET_KEY`) instead of an OAuth token. If your `SECRET_KEY` is compromised AND someone has access to your database, they could decrypt the Dexcom password. The mitigations are: keep your `SECRET_KEY` secret, don't reuse passwords across services, and use a long generated string for `SECRET_KEY`.

If Dexcom's developer API becomes practical for hobbyist projects (rate limits relaxed, approval streamlined), this project will move to it. Until then, this is the path that works.

## Which Dexcom models work?

Any Dexcom CGM that uploads to Dexcom's cloud through the standard Dexcom mobile app should work -- this includes Dexcom G7 and Dexcom G6, since both stream to the same Dexcom cloud the platform reads from. The platform's daily testing is on G7, so G7 is the most validated model; G6 is expected to work but has had less direct testing.

If you have a non-Dexcom CGM (Freestyle Libre, Medtronic Guardian, Eversense, etc.) the direct Dexcom integration won't work, but the [Nightscout integration](./integrations.md#nightscout) does -- upload to a Nightscout site from your CGM's bridge (xDrip+ for Libre, LibreLinkUp-Uploader, etc.) and connect that Nightscout to GlycemicGPT. Anything that flows into Nightscout flows in here.

## Still stuck?

If the integration says **Connected** but glucose isn't updating, see [BG isn't updating -- Dexcom path](../troubleshooting/bg-not-updating.md#dexcom-g7-path).

If the integration won't accept your credentials, sign in at [dexcom.com](https://www.dexcom.com) directly with the same email and password to confirm they work. If the Dexcom website rejects them, your account itself has an issue -- contact Dexcom support.
