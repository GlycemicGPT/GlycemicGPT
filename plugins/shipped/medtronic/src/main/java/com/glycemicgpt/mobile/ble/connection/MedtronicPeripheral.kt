/*
 * Peripheral-mode BLE transport seam for the Medtronic MiniMed 700-series read-only driver.
 *
 * The phone is the BLE peripheral and the pump is the central (the inverted topology vs Tandem --
 * see medtronic-ble-reverse-engineering.md Sec. 3), so there is no Tandem GATT-client equivalent to
 * reuse. This interface abstracts the Android BluetoothLeAdvertiser + BluetoothGattServer plumbing
 * (implemented by AndroidMedtronicPeripheral, modelled on OpenMinimed's JavaPumpConnector
 * BlePeripheralDevice, GPL-3.0, used with permission) so the connection lifecycle in
 * MedtronicBleConnectionManager can be driven and unit-tested without the Android BLE stack.
 */
package com.glycemicgpt.mobile.ble.connection

import com.glycemicgpt.mobile.ble.protocol.MedtronicProtocol

/**
 * Which SAKE service the phone advertises, selecting the 16-bit service-class UUID the pump scans
 * for (medtronic-ble-reverse-engineering.md Sec. 3):
 *
 *  - [FIRST_PAIR] advertises `0xFE82` for an initial pairing.
 *  - [RECONNECT] advertises `0xFE81` (the reconnect bit-flip) for an already-paired pump, at a
 *    shorter advertising interval because the pump scans infrequently to save battery (Sec. 7).
 *
 * The interval choice is the implementation's concern; this enum only fixes the advertised service.
 */
enum class AdvertisingMode(val serviceUuid16: Int) {
    FIRST_PAIR(MedtronicProtocol.SAKE_SERVICE_FIRST_PAIR_16),
    RECONNECT(MedtronicProtocol.SAKE_SERVICE_RECONNECT_16),
}

/**
 * Events the [MedtronicPeripheral] surfaces from the Android GATT-server / advertiser callbacks.
 *
 * Implementations deliver these from the binder thread; the listener must not block (the
 * connection manager hands SAKE work straight to a worker thread).
 */
interface PeripheralListener {
    /** Advertising started successfully in [mode]. */
    fun onAdvertiseStarted(mode: AdvertisingMode)

    /** Advertising could not start (e.g. peripheral mode unsupported, too many advertisers). */
    fun onAdvertiseFailed(errorCode: Int)

    /** A central (the pump) opened a connection to the GATT server. */
    fun onPumpConnected(address: String)

    /** The pump enabled notifications on the SAKE characteristic -- the cue to emit the wake-up. */
    fun onSakeSubscribed()

    /** The pump disabled notifications on the SAKE characteristic (a mid-handshake resubscribe aborts). */
    fun onSakeUnsubscribed()

    /** The pump wrote [value] to the SAKE characteristic (a handshake or session frame). */
    fun onSakeWrite(value: ByteArray)

    /** The central disconnected; [status] is the GATT status code from the stack. */
    fun onPumpDisconnected(status: Int)
}

/**
 * Phone-as-peripheral BLE transport: advertise as a "Mobile …" device and stand up the read-only
 * GATT server (SAKE + Device Information) the 700-series pump connects to.
 *
 * The GATT server is opened once via [start] and persists across advertising changes; [advertise]
 * switches the advertised service/interval (e.g. first-pair -> reconnect) without tearing it down.
 * All methods are no-ops when the underlying adapter is unavailable.
 */
interface MedtronicPeripheral {
    /**
     * Whether this device can advertise as a BLE peripheral at all. Emulators and some chipsets
     * cannot (medtronic-ble-reverse-engineering.md Sec. 3); the device support matrix is filled in
     * live in 48.A2.
     */
    fun isSupported(): Boolean

    /**
     * Open the GATT server and begin advertising in [mode] under [localName] (which must match
     * `Mobile .{0,7}`), routing subsequent events to [listener]. Safe to call again to re-advertise.
     */
    fun start(mode: AdvertisingMode, localName: String, listener: PeripheralListener)

    /** Switch the advertised service/interval (e.g. [AdvertisingMode.RECONNECT]) without closing the GATT server. */
    fun advertise(mode: AdvertisingMode, localName: String)

    /** Stop BLE advertising while keeping the GATT server open. */
    fun stopAdvertising()

    /**
     * Notify the connected pump on the SAKE characteristic. Returns `false` if there is no
     * subscribed peer or the stack rejects the notification. The payload must already be a single
     * <= 20-byte PDU (the manager fragments before calling this).
     */
    fun sendSakeNotification(payload: ByteArray): Boolean

    /** Best-effort removal of the OS-level BLE bond for [address] (used by unpair). */
    fun removeBond(address: String): Boolean

    /** Stop advertising and close the GATT server, releasing all BLE resources. */
    fun stop()
}
