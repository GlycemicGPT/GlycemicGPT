---
title: Install the Android App
description: Step-by-step Android install for the GlycemicGPT companion app.
---

The Android companion app is **required** to connect your insulin pump over Bluetooth. The platform alone cannot read pump data via Bluetooth -- the phone app handles that.

This guide covers installing the app on your phone. It assumes you've already got the platform running (see [Get Started](../get-started.md) if not).

> **Before you start, you need:**
>
> - An Android phone running **Android 11 or newer**
> - Bluetooth support (essentially every phone made in the past decade)
> - The platform already running and reachable -- either at `http://<your-computer-ip>:3000` (local) or `https://yourdomain.com` (always-on deployment). If you don't know your computer's IP, see the box below.
> - The platform URL written down -- you'll paste it into the app

> **iOS / iPhone:** Today only Android is supported. iOS is on the roadmap (see [ROADMAP.md](../../ROADMAP.md)) but not available yet. If you only have an iPhone, you can still use the dashboard in your phone's browser -- you just won't get live pump data without an Android phone for the companion app.

> **How to find your computer's IP address (for "trying it locally"):**
>
> - **macOS:** Apple menu → System Settings → Network → click your active connection (Wi-Fi or Ethernet) → look for "IP Address."
> - **Windows:** Settings → Network & Internet → click your connection → look for "IPv4 address."
> - **Linux (Ubuntu / Fedora / etc.):** open a terminal and run `ip addr show` -- look for the `inet` line under your active network adapter (usually `wlan0` for Wi-Fi or `eth0`/`enp...` for Ethernet).
>
> The IP usually starts with `192.168.` or `10.0.` -- something like `192.168.1.42`. Your platform URL will then be `http://192.168.1.42:3000`.

> **For the local path, your phone must be on the same Wi-Fi as the computer running the platform.** The "trying it locally" mode only works on your home network -- if you want to use the dashboard from work, the grocery store, etc., you need an [always-on deployment](../get-started.md#choose-your-path).

## Step 1: Download the APK

GlycemicGPT ships its Android app as a signed APK on GitHub Releases.

1. Open [github.com/GlycemicGPT/GlycemicGPT/releases](https://github.com/GlycemicGPT/GlycemicGPT/releases) on your phone (or a computer)
2. Find the **latest stable release** -- the topmost entry on the page *without* a yellow "Pre-release" label. (GitHub uses the "Pre-release" label for in-progress builds that haven't been promoted to stable yet.)
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

> **Heads up:** This path requires using your computer's terminal -- the same text-based command interface used in [Get Started](../get-started.md#a-note-on-the-terminal). If you're not comfortable with the terminal, ask someone who is, or skip Path B and use Path A instead. Path A (tap the APK on your phone) works for the vast majority of users.

What you'll need:

- A computer with **Android Platform Tools** installed -- this is what gives you the `adb` command. Install with:
  - **macOS:** `brew install android-platform-tools` (requires [Homebrew](https://brew.sh))
  - **Linux:** `sudo apt install android-tools-adb` (Ubuntu/Debian) or `sudo dnf install android-tools` (Fedora)
  - **Windows:** download the [Platform Tools zip](https://developer.android.com/tools/releases/platform-tools), unzip, and add the folder to your PATH (or just run `adb.exe` from the unzipped folder)
- A USB cable, OR wireless ADB enabled on the phone (Wi-Fi networking only)
- Developer Options enabled on the phone -- this is a one-time setting:
  1. On your phone, open **Settings → About phone**
  2. Tap **Build number** seven times in quick succession. The phone will say "You are now a developer."
- USB debugging enabled (Settings → Developer Options → USB debugging)

Once you have all that, plug your phone into your computer with the USB cable. Open a terminal on your computer (see [the terminal note in Get Started](../get-started.md#a-note-on-the-terminal) if you're new to it), navigate to the folder where you downloaded `app-release.apk`, then run:

```bash
adb install app-release.apk
```

What this does: `adb` (Android Debug Bridge) sends the APK file to the phone over USB and triggers an install. The phone might show a "USB debugging authorization" prompt the first time you do this -- accept it, and check "Always allow from this computer" so you don't get prompted again.

If you see `Performing Streamed Install ... Success`, the app is installed -- find it in your phone's app drawer and open it.

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
2. Tap **Pair pump**. The app asks for permission to use Bluetooth and Location (Android requires Location for Bluetooth scanning -- this is an OS quirk; the app does not track your location).
3. Put your pump in pairing mode (consult your pump's manual -- on Tandem t:slim X2, this is **Options → Bluetooth Settings → Pair Device**).
4. The app discovers your pump and asks for the 6-digit pairing code shown on the pump's screen. Enter it.
5. The app and pump exchange pairing keys. This takes a few seconds.

Once paired, the app stays connected to the pump in the background and forwards live data (insulin on board, basal rate, glucose, battery, reservoir) to your platform.

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

- **Battery and Bluetooth:** the app stays connected to your pump in the background, which uses some battery. On most phones the impact is small (< 5% per day) because Tandem's Bluetooth protocol is energy-efficient. If you see your phone disconnecting from the pump frequently, your phone's battery optimization may be killing the app -- exempt GlycemicGPT in Settings → Battery → Battery optimization.
- **No insulin delivery:** the app is read-only. It does not deliver bolus, change basal rates, or modify any pump setting. See [What This Software Is and Isn't](../concepts/what-this-software-is-and-isnt.md) for the project's monitoring-only stance.
- **Single device pairing:** Tandem pumps allow only one Bluetooth connection at a time. If your pump is already paired with another app (the official t:connect app, for example), unpair it first -- only one phone can be connected.
