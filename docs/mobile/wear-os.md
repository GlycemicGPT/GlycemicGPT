---
title: Install the Wear OS Watch Face
description: Optional at-a-glance glucose monitoring on a Wear OS watch.
---

GlycemicGPT ships an optional Wear OS watch face that shows your glucose, trend arrow, insulin on board, and time at a glance. **It's optional** -- the platform and mobile app work without it.

> **The watch face is harder to install than the phone app.** Wear OS doesn't allow APK downloads from the watch's browser, so installing requires connecting the watch to a computer over ADB. If that sounds like more than you want to deal with, skip this -- the phone app gives you everything important.

## What you'll need

- A Wear OS watch running **Wear OS 5 or newer** (API 35+). Newer watches running **Wear OS 6** (API 36+) get a smoother experience -- the phone app can push the watch face to them automatically.
- The GlycemicGPT phone app already installed and signed in (see [Install the Android App](./install.md))
- Your phone and watch already paired through the Wear OS app
- A computer with **Android Platform Tools** installed -- this gives you the `adb` command. Install with:
  - **macOS:** `brew install android-platform-tools` (requires [Homebrew](https://brew.sh))
  - **Linux:** `sudo apt install android-tools-adb` (Ubuntu/Debian) or `sudo dnf install android-tools` (Fedora)
  - **Windows:** download the [Platform Tools zip](https://developer.android.com/tools/releases/platform-tools), unzip, and add the folder to your PATH
- Comfort with running commands in a terminal -- if you've never done that, see the [terminal note in Get Started](../get-started.md#a-note-on-the-terminal)
- USB cable or willingness to use wireless ADB

> **Heads up:** The watch install steps below are the most technical part of setting up GlycemicGPT. If they feel beyond what you want to deal with, skip the watch face -- the phone app gives you everything important. The roadmap includes a smoother installation path (Watch Face Push API expansion, possibly Play Store distribution) but that's not available yet.

## How it works (so the steps below make sense)

The watch face is two pieces:

1. **`wear-device`** -- a small Wear OS app that runs on the watch. It listens for data the phone forwards (glucose, IoB, etc.) and provides complications.
2. **`watchface`** -- the actual watch face APK (built using Watch Face Format, WFF).

Depending on your watch's Wear OS version, the procedure is slightly different:

- **Wear OS 6+ watches**: install `wear-device` once via ADB. From then on, the phone app pushes the watch face directly using the Watch Face Push API. This is the easier path.
- **Wear OS 5 watches**: install both `wear-device` and `watchface` via ADB. The phone app cannot push faces to Wear OS 5; the face is a regular installed APK.

Not sure which you have? Open Settings on your watch, scroll to **System → About → Versions**. If Wear OS version is 6.x or newer, you're on the easier path.

## Step 1: Enable developer mode on your watch

1. On the watch, go to **Settings → System → About → Versions**
2. Tap **Build number** seven times. The watch will say "You are now a developer."
3. Go back to **Settings → Developer Options**, enable **ADB debugging** and **Debug over Wi-Fi** (or **Debug over Bluetooth** depending on your watch).

The watch will show an IP address and port at the top of the Developer Options screen -- something like `192.168.1.42:5555`. Note it.

## Step 2: Connect ADB to the watch

The exact command depends on your watch and connection:

### Option A: Wireless ADB (most common -- no cable needed)

On your computer:

```bash
adb connect 192.168.1.42:5555
```

Replace the IP and port with what your watch shows. The watch will pop a dialog asking to allow ADB access -- accept it. (You may need to also tap "Always allow from this computer" so you don't get prompted again.)

Verify the connection:

```bash
adb devices
```

You should see your watch listed.

### Option B: USB ADB (if your watch has a USB charging cradle)

Plug the watch into the cradle, plug the cradle into your computer's USB port. Run `adb devices` -- the watch should appear.

## Step 3: Download the watch APKs

1. Open [github.com/GlycemicGPT/GlycemicGPT/releases](https://github.com/GlycemicGPT/GlycemicGPT/releases)
2. From the latest release, download:
   - `wear-device-release.apk` -- always needed
   - `watchface-release.apk` -- only needed for Wear OS 5 watches (Wear OS 6+ users skip this)

## Step 4: Install on the watch

If your watch is the only Android device connected over ADB, this works:

```bash
# Install wear-device (always)
adb install wear-device-release.apk

# Wear OS 5 only -- also install the watch face
adb install watchface-release.apk
```

If you have both your phone and watch connected, list devices first to find your watch's serial:

```bash
adb devices
# Output (example):
# 192.168.1.42:5555    device    <- watch
# RF8M21XXXXX          device    <- phone
```

Then target the watch explicitly:

```bash
adb -s 192.168.1.42:5555 install wear-device-release.apk
adb -s 192.168.1.42:5555 install watchface-release.apk  # Wear OS 5 only
```

`Success` means the install worked.

## Step 5 (Wear OS 6+ only): Push the watch face from the phone

Open the GlycemicGPT phone app, go to **Settings → Watch**.

The app should detect your connected watch. Tap **Push watch face**. The phone uploads the WFF APK to the watch via the Watch Face Push API; the watch face appears in your watch's available faces almost immediately.

To switch to it: long-press the current watch face on your watch, scroll through the faces, find **GlycemicGPT** and tap to activate. (Or use the face customization screen on your phone.)

## Step 6 (Wear OS 5 only): Switch to the GlycemicGPT face

You already installed it in step 4. Long-press the current watch face on your watch, scroll through the available faces, find **GlycemicGPT**, tap to activate.

## Step 7: Confirm data is flowing

Within a minute, the watch face should show:

- Your latest glucose reading
- A trend arrow (up / down / flat)
- Your insulin on board (IoB)
- Current time

If the watch face shows `--` for glucose for more than 5 minutes after a fresh setup:

- Make sure the phone app is signed in and your pump/CGM is connected
- Make sure your watch is connected to your phone (Wear OS app shows "Connected")
- Open the GlycemicGPT phone app once -- it sometimes needs a manual nudge to start forwarding to the watch

## Updating the watch face

When a new GlycemicGPT release ships:

- **Wear OS 6+:** open the phone app, go to **Settings → Watch**, tap **Push watch face** again. The new face replaces the old one.
- **Wear OS 5:** download the new `wear-device-release.apk` and `watchface-release.apk`, run `adb install -r` to upgrade in place:
  ```bash
  adb -s <watch-serial> install -r wear-device-release.apk
  adb -s <watch-serial> install -r watchface-release.apk
  ```

## A few honest notes

- **The Wear OS install is genuinely the most complicated step in setting up GlycemicGPT.** ADB to a watch is a developer-grade workflow. The roadmap includes a smoother distribution path (Watch Face Push API expansion, possibly Play Store distribution) but it's not there yet.
- **The watch face is read-only.** No interactions with it can deliver insulin, change pump settings, or modify your data.
- **Battery impact on the watch:** the face is a normal Wear OS face that updates once per glucose reading interval (~5 minutes). Battery cost is similar to other glucose-monitoring watch faces.
