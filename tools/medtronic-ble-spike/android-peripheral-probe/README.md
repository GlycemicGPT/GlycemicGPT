# Peripheral-mode capability probe

The Medtronic 700-series BLE topology is **inverted** versus our Tandem driver: the **phone is the
BLE peripheral** (it advertises as a "Mobile" device — company id `0x01f9`, SAKE service `0xFE82`)
and the **pump connects to it as the central**. So before building the driver we have to answer one
hardware question: *can the target device act as a BLE peripheral at all?* Peripheral advertising
(`BluetoothLeAdvertiser` + `BluetoothGattServer`) is **not universal** on Android.

[`PeripheralModeProbe.kt`](PeripheralModeProbe.kt) answers that question on any device it runs on.
It records observed facts — `getBluetoothLeAdvertiser() != null`,
`isMultipleAdvertisementSupported()`, whether `openGattServer()` + `addService(0xFE82)` succeed, and
whether `startAdvertising()` reports success or an error code — into a `PeripheralCapability` result.

## Why this is reference code, not a wired module

This spike's Gradle project is pure JVM (so the SAKE handshake is provable with no Android SDK and
no device). The probe is **Android** code and depends on the BLE radio, so it is committed here as
the proven reference the production `MedtronicBleConnectionManager` is built from, not as a compiled
module. To run it now:

1. Drop `PeripheralModeProbe.kt` into a debug build of `:app` behind a developer toggle.
2. Grant the BLE runtime permissions (`BLUETOOTH_ADVERTISE` + `BLUETOOTH_CONNECT` on API 31+;
   `ACCESS_FINE_LOCATION` below).
3. Call `probe()` on a **physical device** and log the `PeripheralCapability`.

## Support matrix

Peripheral advertising **cannot be emulated** — the Android emulator's Bluetooth stack has no radio,
so `getBluetoothLeAdvertiser()` returns `null` (or `isMultipleAdvertisementSupported()` is `false`)
and no central can ever connect. This is a documented, well-known Android limitation, not a probe
bug. Therefore the emulator row below is an authoritative known-negative, and the live device rows
are filled by running the probe on real hardware.

| Device / image | API | Advertiser present | GATT server | Advertises 0xFE82 | Peripheral-capable | Source |
|---|---|---|---|---|---|---|
| Android emulator (any system image) | any | ❌ no radio | n/a | n/a | **❌ NO** | Documented Android limitation; confirmed by the probe returning `advertiserPresent = false` |
| Physical device — OpenMinimed reference | — | ✅ | ✅ | ✅ | **✅ YES** | OpenMinimed `JavaPumpConnector` runs this exact peripheral path against real 780G pumps |
| _devbox physical phone_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _run probe_ | live follow-up |
| _beta-tester device(s)_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _run probe_ | live follow-up |

**Status in this offline spike:** the capability probe + GATT-server/advertiser model are written
and documented; the emulator known-negative is recorded. The *live* "advertise to a real pump and
have it connect" demonstration requires both a peripheral-capable phone and a 700-series pump, so it
belongs to the hardware-gated live follow-up, which fills the device rows above. OpenMinimed's
`JavaPumpConnector` already runs this peripheral path successfully against real pumps, so the model
is proven upstream; what remains is confirming it on our specific device matrix.

## Implementation notes carried into the production driver

- **Advertise → connect → stop:** start advertising connectable; when a central connects, stop
  advertising; on disconnect, restart. (Mirror `JavaPumpConnector.BlePeripheralDevice`.)
- **Serialize SAKE off the binder thread:** drive the handshake on a dedicated `HandlerThread`, not
  in the GATT callbacks (which fire on a binder thread). See `JavaPumpConnector.SakeHandler`.
- **Wake-up frame:** when the pump subscribes to notifications on `0xFE82`, the phone emits a
  20-byte zero "wake-up" notification; the pump replies with its own 20 zero bytes, which the phone
  feeds to `SakeServer.handshake(...)` to get msg0.
- **Graceful degradation:** if `isPeripheralCapable` is false, surface a clear
  "this device can't pair a Medtronic pump over Bluetooth" message rather than failing silently
  (the documented peripheral-mode device-gap risk).
