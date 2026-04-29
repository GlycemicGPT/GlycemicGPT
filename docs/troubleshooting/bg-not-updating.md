---
title: BG isn't updating
description: The dashboard loads but glucose values are stale or missing.
---

The dashboard opens, you can sign in, but your glucose readings aren't current -- or there are no readings at all. Glucose data has to flow from your device through the mobile app and into the platform; this page walks the path looking for the broken link.

> **Glucose data is time-sensitive.** If you suspect the dashboard is showing wrong or stale data, check your CGM's official app to confirm the actual reading. The dashboard is for monitoring -- never make medical decisions based on a value the dashboard shows without verifying it.

## What is your data path?

Two real paths today, with different things to check:

| Your CGM | Path glucose data takes |
|---|---|
| Dexcom G7 | Dexcom Cloud → GlycemicGPT API directly (the mobile app is **not** in this path for Dexcom) |
| Tandem t:slim X2 with built-in CGM stream | Pump → mobile app over Bluetooth → platform |

If you only use a Dexcom G7 and don't have a Tandem pump, **the mobile app is not in the glucose data path** -- the platform pulls from Dexcom Cloud directly. Skip to the Dexcom section.

If you have a Tandem pump that streams CGM data, the mobile app is the data path. Use the Tandem section.

## Dexcom G7 path

The platform polls Dexcom Cloud on a configurable interval. If the dashboard isn't updating, check:

### Is the Dexcom integration configured and connected?

In the dashboard, go to **Settings → Integrations → Dexcom**. The status should show **Connected** with a recent last-sync time.

- **Status: Disconnected** -- credentials missing or expired. Re-enter your Dexcom Share account credentials.
- **Status: Auth Error** -- Dexcom rejected the credentials. Double-check the Share account password by signing in at [dexcom.com](https://www.dexcom.com).
- **Status: Connected, last sync was hours ago** -- the polling job may have stalled. Check API logs: `docker compose logs --tail=100 api | grep -i dexcom`.

### Is your CGM actually transmitting data?

Verify in the official Dexcom G7 app on your phone that it's receiving readings. If the official app doesn't show recent data, the issue is upstream of GlycemicGPT (sensor expired, transmitter battery, sensor not reading) -- the platform can only sync what Dexcom has.

### Are you using a Dexcom G6 instead of G7?

GlycemicGPT supports G7 today. G6 is not currently supported. Check the latest [ROADMAP](../../ROADMAP.md) for additional CGM support.

## Tandem (mobile app) path

Glucose data from a Tandem pump's CGM stream flows over Bluetooth to the mobile app, then to the platform. Several places this can break.

### Is the mobile app connected to the pump?

Open the GlycemicGPT phone app. The home screen shows a connection status indicator near the top.

- **Indicator says Connected, recent reading** -- pump is connected and forwarding data. Issue is between the app and the platform; skip to the next section.
- **Indicator says Disconnected or Searching** -- the app isn't talking to your pump. Common causes:
  - Pump out of range (Bluetooth range is ~10 meters, less through walls)
  - Pump's BLE turned off (check pump: Options → Bluetooth Settings → On)
  - Phone's Bluetooth turned off
  - Pump paired with another app (only one BLE connection at a time)
  - Phone killed the app in the background (Android battery optimization)

### Is the app paired but not getting glucose data specifically?

The mobile app reads multiple data types from the pump: insulin on board, basal rate, glucose, battery, reservoir. If basal/IoB are updating but glucose isn't, the pump's CGM stream specifically is the issue.

- Verify on the pump itself that it's currently displaying glucose readings (not "---" or "NO CGM")
- The CGM transmitter needs to be paired with the pump. If you're using a Dexcom G7 with a Tandem pump, the G7 has to be paired with the pump separately from the Tandem-app pairing -- consult your pump's manual for the CGM pairing flow.

### Is the app forwarding data to the platform?

If the app shows live glucose but the dashboard doesn't, the app-to-platform sync is broken.

- In the phone app, **Settings → Server** -- verify the Server URL is correct and reachable from your phone
- Check the app's connection status to the platform -- there should be an indicator
- Common causes:
  - Phone is on a different network than the platform (only matters for laptop / local-network deployments without public access)
  - Platform's `CORS_ORIGINS` doesn't include the URL the app is using
  - The platform's API is down -- check `docker compose ps`

### Did the platform recently restart?

A platform restart kills the app's session. Open the phone app, sign out, sign back in. If readings resume, the session was the issue.

## Common to both paths: check the API for ingest errors

The clearest signal of "data is arriving but failing to write" comes from the API logs:

```bash
docker compose logs --tail=200 api | grep -iE "glucose|cgm|ingest|reading"
```

Errors here are usually:
- **Validation error: glucose value out of range** -- a reading was rejected because it was outside the platform's safety limits (typically 20-500 mg/dL). The platform is protecting you from displaying garbage values; the upstream device is reporting weird data.
- **Database error** -- the database container may be unhealthy. Check `docker compose ps`.

## Battery optimization on Android

If the phone app drops the pump connection multiple times per day, Android's battery optimization is probably killing the app in the background.

On most Android phones:

- Settings → Battery → Battery optimization
- Find GlycemicGPT in the list
- Set to **Don't optimize** (or "Unrestricted" / "No restrictions" depending on phone manufacturer)

Samsung phones have an additional "Sleeping apps" list under Settings → Apps → GlycemicGPT → Battery. Make sure GlycemicGPT isn't there.

## Still stuck?

Capture this and bring it to [Discord](https://discord.gg/QbyhCQKDBs):

- Which CGM you have (Dexcom G7, Tandem-built-in, etc.)
- Whether your pump uses a CGM stream
- The status indicators in the phone app (paired / connected / etc.)
- The most recent ~50 lines of API logs:
  ```bash
  docker compose logs --tail=50 api
  ```
