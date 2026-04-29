---
title: Can't pair pump
description: The mobile app can't find or connect to your insulin pump.
---

You opened the GlycemicGPT phone app, tapped **Pair pump**, and something went wrong -- the app didn't find the pump, the pairing code was rejected, or the connection drops immediately. Here's the path through the most common causes.

## Check pairing prerequisites first

These are the boring causes. Walk through them before assuming anything's broken:

- **Bluetooth is on** on your phone (Settings → Bluetooth)
- **Location is enabled** for the GlycemicGPT app (Android requires Location permission for any Bluetooth scan; this is an OS-level requirement, the app does not track your location)
- **The pump is in pairing mode** -- on Tandem t:slim X2, this is **Options → Bluetooth Settings → Pair Device**. The pump shows a 6-digit code while it's in pairing mode. The code times out after a couple of minutes -- if the app didn't connect by then, restart pairing on the pump.
- **The pump is within Bluetooth range** -- a couple of meters, ideally on the same desk as your phone during pairing. Range can be much shorter through walls.
- **Battery on both devices** -- a low-battery pump or phone can flake out during Bluetooth handshakes.

## Symptom: the app doesn't find the pump at all

The app shows "Searching..." and never lists your pump.

### Is the pump actually advertising?

Tandem pumps only advertise themselves over Bluetooth when in pairing mode. If you opened pairing on the pump but the app didn't see anything, try:

1. Cancel pairing on the pump (back out of the menu)
2. Force-stop the GlycemicGPT app on your phone
3. Open the app again, tap **Pair pump**
4. **Then** open pairing on the pump

Order matters here -- the app needs to be actively scanning when the pump starts advertising.

### Is another app already connected to the pump?

**Tandem pumps only allow one Bluetooth connection at a time.** If your phone (or another phone) is already connected to the pump via the official t:connect app or any other Bluetooth app, GlycemicGPT can't connect.

Disconnect the other app first:

- In the official t:connect app: **Settings → Pump Settings → Forget pump** (or similar -- consult t:connect documentation)
- On the phone: Settings → Bluetooth → find your pump, tap settings/info, tap **Forget**

Then retry pairing in the GlycemicGPT app.

### Is your phone too old?

The app requires Android 11 or newer (API 30+). On older phones, Bluetooth permissions and stack behavior differ enough that the app may scan but not see anything. Check your Android version: Settings → About phone → Android version.

## Symptom: the pump shows up but the pairing code is rejected

The app discovers your pump, but when you enter the 6-digit code, it returns an error.

- **Re-enter the code carefully.** It's easy to mis-read a 6 as an 8 on the pump's screen.
- **Don't let the code time out.** The pump only accepts the code for a couple of minutes after pairing mode starts. If you took too long, restart pairing on the pump and try again.
- **Use the correct field.** GlycemicGPT shows two fields during pairing -- one for the pump's code, one to confirm. Make sure you typed the code in the right one.

## Symptom: pairing succeeds but the connection drops within seconds

The pairing handshake completes, the app shows "Connected" briefly, then drops back to "Disconnected" or "Searching."

### Is your phone's battery optimization killing the app?

Android aggressively suspends apps in the background. For Bluetooth pump connections to stay live, the app needs to be exempted:

- Settings → Battery → Battery optimization
- Find **GlycemicGPT** in the list
- Set to **Don't optimize** (or "Unrestricted" / "No restrictions" -- the wording varies by manufacturer)

Samsung phones additionally have a "Sleeping apps" list (Settings → Apps → GlycemicGPT → Battery). Make sure GlycemicGPT isn't on it.

### Is the pump's Bluetooth flaky?

Tandem pumps occasionally have Bluetooth issues that resolve with a power cycle:

1. Power off the pump (consult your pump's manual; this is not "remove the battery" -- use the proper power-off sequence)
2. Wait 10 seconds
3. Power back on
4. Try pairing again

This is also a good thing to try after a pump firmware update.

### Is your phone case interfering?

Some metal phone cases or cases with embedded magnets degrade Bluetooth signal. If you've got a heavy-duty case, try pairing without it once and see if that changes anything.

## Symptom: "the pump is paired but data isn't flowing"

Pairing finished without errors, the app shows "Connected," but no glucose / insulin data shows up. That's a different problem -- see [BG isn't updating](./bg-not-updating.md).

## Tandem Mobi specifically

The Tandem Mobi pump uses the same Bluetooth protocol as the t:slim X2, but the platform has not been verified against physical Mobi hardware (see [README](../../README.md) Mobi note for the disclaimer). Pairing with Mobi may work but is at your own risk. If you have a Mobi and successfully pair, please [open an issue](https://github.com/GlycemicGPT/GlycemicGPT/issues/new/choose) reporting your experience -- it helps the project understand whether Mobi support is solid in practice.

## Still stuck?

Capture this and bring it to [Discord](https://discord.gg/QbyhCQKDBs):

- Your pump model (t:slim X2, Mobi)
- Your phone model and Android version
- What the app shows (Searching / Found / Connected / Error message)
- Whether the pump is currently paired with anything else (t:connect, Sugarmate, etc.)
