---
title: Install the Android App
description: Step-by-step Android install for the GlycemicGPT companion app.
---

The Android companion app is **required** to connect your insulin pump over Bluetooth. The platform alone cannot read pump data via Bluetooth -- the phone app handles that.

This guide covers installing the app on your phone. It assumes you've already got the platform running (see [Get Started](../get-started.md) if not).

> **Before you start, you need:**
>
> - An Android phone running **Android 11 or newer** (API 30+)
> - Bluetooth Low Energy support (essentially every modern phone)
> - The platform already running and reachable -- either at `http://<your-computer-ip>:3000` (local) or `https://yourdomain.com` (always-on deployment)
> - The platform URL written down -- you'll paste it into the app

## Step 1: Download the APK

GlycemicGPT ships its Android app as a signed APK on GitHub Releases.

1. Open [github.com/GlycemicGPT/GlycemicGPT/releases](https://github.com/GlycemicGPT/GlycemicGPT/releases) on your phone (or a computer)
2. Find the **latest stable release** (the topmost release that isn't tagged "Pre-release")
3. Under **Assets**, download `app-release.apk`

If you'd rather get the latest development build (newer features, less tested), use the [`dev-latest` pre-release](https://github.com/GlycemicGPT/GlycemicGPT/releases/tag/dev-latest) and download `app-debug.apk` instead.

> **Stable vs dev:** If you're new to GlycemicGPT, use the stable release. The dev build is what the project lead runs daily, but it's where new bugs surface first.

## Step 2: Install the APK

Android blocks installs of APKs not from the Play Store by default. You'll need to allow it for the file manager / browser you used to download the APK -- a one-time permission.

### Path A: Install directly on your phone (most common)

1. On your phone, open the file manager (or your browser's downloads list) and tap `app-release.apk`
2. Android will show: *"For your security, your phone is not allowed to install unknown apps from this source."* Tap **Settings**.
3. Toggle **Allow from this source** to ON. Go back.
4. Tap **Install**.
5. After installation, tap **Open**.

### Path B: Sideload via ADB (if Path A doesn't work)

Some phones, work-managed devices, or devices in restrictive corporate / family settings block APK installs entirely from the file manager. In that case, you can install over USB or wireless ADB from a computer.

What you'll need:
- A computer with [Android Platform Tools](https://developer.android.com/tools/releases/platform-tools) (Linux: `apt install adb`, macOS: `brew install android-platform-tools`)
- USB cable or wireless ADB enabled on the phone
- Developer Options enabled on the phone (tap Settings → About phone → Build number 7 times)
- USB debugging enabled (Settings → Developer Options → USB debugging)

Connect the phone, then:

```bash
adb install path/to/app-release.apk
```

If you see `Performing Streamed Install ... Success`, the app is installed.

If you see `INSTALL_FAILED_USER_RESTRICTED`, your phone has installs from sources other than the Play Store blocked at the policy level -- common on work-managed devices. Talk to your IT admin or use a personal device.

## Step 3: Open the app

Find **GlycemicGPT** in your app drawer and tap to open.

The first launch shows an onboarding flow:

1. **Server URL** -- paste your platform's address. Examples:
   - Trying it locally with the platform on the same network: `http://192.168.1.50:3000` (replace with your computer's local IP -- find it in System Settings → Network)
   - Always-on deployment: `https://glycemicgpt.yourdomain.com`
2. **Sign in** -- use the email and password you registered in step 7 of [Get Started](../get-started.md).

If the app says it can't connect, your phone can't reach the platform. Common causes:
- Trying it locally but your phone is on a different Wi-Fi network than the platform
- A firewall on your computer blocking inbound connections to port 3000
- The platform's `CORS_ORIGINS` doesn't include the URL you typed -- check `.env` and restart the API service if you change it

## Step 4: Pair your pump

This is the part the platform alone cannot do.

1. Once signed in, the app shows a dashboard. If no pump is paired, you'll see a "Pair pump" prompt.
2. Tap **Pair pump**. The app asks for permission to use Bluetooth and Location (Android requires Location for BLE scanning -- this is an OS quirk; the app does not track your location).
3. Put your pump in pairing mode (consult your pump's manual -- on Tandem t:slim X2, this is **Options → Bluetooth Settings → Pair Device**).
4. The app discovers your pump and asks for the 6-digit pairing code shown on the pump's screen. Enter it.
5. The app and pump exchange pairing keys. This takes a few seconds.

Once paired, the app stays connected to the pump in the background and forwards live data (IoB, basal, glucose, battery, reservoir) to your platform.

## Step 5: Confirm data is flowing

Open your dashboard at the platform's URL. You should see:

- A glucose chart populating with recent readings
- Insulin on Board (IoB) updating
- Basal rate and reservoir level under the pump status

If the dashboard is still empty after 5 minutes, see [Troubleshooting -- BG isn't updating](../troubleshooting/bg-not-updating.md).

## Updating the app

When a new GlycemicGPT release ships, you'll see a stale-version banner in the app. To update:

1. Download the new `app-release.apk` from the latest release on GitHub
2. Open it on your phone -- Android handles it as an "in-place upgrade"
3. The app reopens with the new version; your settings, login, and pump pairing are preserved

The app does not auto-update -- there's no Play Store distribution today. F-Droid and Play Store distribution are on the roadmap.

## A few notes

- **Battery and Bluetooth:** the app stays connected to your pump in the background, which uses some battery. On most phones the impact is small (< 5% per day) because Tandem's BLE protocol is energy-efficient. If you see your phone disconnecting from the pump frequently, your phone's battery optimization may be killing the app -- exempt GlycemicGPT in Settings → Battery → Battery optimization.
- **No insulin delivery:** the app is read-only. It does not deliver bolus, change basal rates, or modify any pump setting. See [What This Software Is and Isn't](../concepts/what-this-software-is-and-isnt.md) for the project's monitoring-only stance.
- **Single device pairing:** Tandem pumps allow only one BLE connection at a time. If your pump is already paired with another app (the official t:connect app, for example), unpair it first -- only one phone can be connected.
