/*
 * GlycemicGPT code (GPL-3.0). Transport seam for the Medtronic 700-series read layer.
 */
package com.glycemicgpt.mobile.ble.read

import java.util.UUID

/**
 * The minimal GATT operations the read layer needs, abstracted so the readers and
 * [MedtronicSessionReader] are transport-agnostic and unit-testable against canned frames.
 *
 * In the inverted topology the pump connects to the phone (peripheral) but exposes its CGM / IDD /
 * Device-Info services as a GATT **server**; over that same link the phone acts as a GATT **client**
 * to read them — exactly as OpenMinimed's PythonPumpConnector does over BlueZ (write the control
 * point, subscribe for notifications, read static characteristics). The concrete Android
 * `BluetoothGatt`-client implementation of this interface is wired in Milestone C3; the connection
 * manager already owns the link and the post-handshake [com.glycemicgpt.mobile.ble.sake.MedtronicSakeSession].
 *
 * All payloads cross this seam as raw bytes; SAKE encryption/decryption is applied above it
 * ([MedtronicSessionReader]), and the 20-byte PDU cap is honored by fragmenting outbound writes via
 * [com.glycemicgpt.mobile.ble.protocol.PduFramer] and reassembling inbound notifications
 * ([NotificationReassembler]). Implementations never call `requestMtu()`.
 *
 * Per the project's BLE guideline, the implementation must time-bound every [read]/[write]/[subscribe]
 * operation (the C3 wiring enforces this); this interface defines no timer of its own.
 */
interface MedtronicGattLink {

    /** Read a static characteristic value (Device Info, Battery Level, CGM Feature). */
    fun read(characteristic: UUID): ByteArray

    /**
     * Write [value] to a characteristic. The caller passes a payload already fragmented to <= 20-byte
     * PDUs when oversized; control-point requests (RACP, SOCP) are small and fit one PDU.
     */
    fun write(characteristic: UUID, value: ByteArray)

    /**
     * Enable notifications/indications on [characteristic] and deliver each inbound PDU to [onPdu].
     * Re-subscribing replaces the handler. Notifications must be effective before any subsequent
     * control-point [write], so the request's response is not missed.
     *
     * **Threading contract:** all [onPdu] callbacks across every subscribed characteristic are
     * delivered serialized on a single thread. [MedtronicSessionReader] relies on this to keep its
     * per-exchange state lock-free; the on-device implementation (C3) must honor it (e.g. by hopping
     * BLE callbacks onto one handler thread, as the connection manager already does).
     */
    fun subscribe(characteristic: UUID, onPdu: (ByteArray) -> Unit)

    /** Disable notifications and drop the handler for [characteristic]. */
    fun unsubscribe(characteristic: UUID)
}
