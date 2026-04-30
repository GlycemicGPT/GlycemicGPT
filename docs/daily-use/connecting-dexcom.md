---
title: Connecting Your Dexcom CGM
description: Hook GlycemicGPT up to your Dexcom account so glucose flows into the dashboard automatically.
---

GlycemicGPT pulls Dexcom data from Dexcom's cloud using your normal Dexcom account credentials. You don't need to do anything on your phone for this; the platform checks Dexcom for new data directly on a schedule.

> **If you're already running Nightscout:** today, GlycemicGPT pulls from Dexcom Share independently of Nightscout. If you also have Nightscout pulling from Dexcom Share, both will hit Dexcom's servers with your credentials -- not broken, but wasteful. The Phase 2 roadmap item for [Nightscout-as-data-source](../concepts/relationship-to-other-tools.md#nightscout) will let GlycemicGPT read from your Nightscout's `/entries.json` instead, eliminating the duplicate. Watch [ROADMAP.md](../../ROADMAP.md) for timing.

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
5. Pick your **server region** (US / OUS for outside-US -- if you're in the US, pick US)
6. Click **Save**

GlycemicGPT stores your credentials encrypted on the platform and uses them to check Dexcom for new data on your behalf. The platform never sends your password anywhere except to Dexcom itself, and you can delete the credentials at any time by disconnecting the integration.

### 3. Wait for the first sync

The integration checks Dexcom for new data on a schedule (typically every 5-10 minutes). The first check happens within a minute of saving credentials. Watch your dashboard -- glucose readings should start appearing.

If after 5-10 minutes you don't see glucose data, see [BG isn't updating](../troubleshooting/bg-not-updating.md).

## How often does it sync?

How often the platform checks Dexcom is configurable -- typical values are 5 to 10 minutes. Checking more often means fresher data on the dashboard but slightly higher load on Dexcom's servers; less often is fine for most users.

You can change this in **Settings → Integrations → Dexcom → Polling interval**.

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

If you have a non-Dexcom CGM (Freestyle Libre, Medtronic Guardian, etc.) it won't work today. Support for additional CGMs and integrations with platforms like Nightscout (which can bridge other CGMs) is on the roadmap -- see [ROADMAP.md](../../ROADMAP.md) §Phase 2.

## Still stuck?

If the integration says **Connected** but glucose isn't updating, see [BG isn't updating -- Dexcom path](../troubleshooting/bg-not-updating.md#dexcom-g7-path).

If the integration won't accept your credentials, sign in at [dexcom.com](https://www.dexcom.com) directly with the same email and password to confirm they work. If the Dexcom website rejects them, your account itself has an issue -- contact Dexcom support.
