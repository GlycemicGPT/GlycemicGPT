package com.glycemicgpt.mobile.domain.plugin

/**
 * Why an [PairingStyle.ADVERTISE_AND_WAIT] pairing attempt is stalled or has failed, surfaced in the
 * pairing UI alongside [com.glycemicgpt.mobile.domain.model.ConnectionState].
 *
 * Central-scan plugins drive their UI from connection state alone and never emit a fault. Advertise-
 * and-wait plugins need this because some failures (this device can't advertise, or the device is
 * still bound to another phone) never produce a connection-state transition -- there is nothing to
 * show without an explicit reason.
 */
enum class PairingFault {
    /** This phone cannot advertise as a BLE peripheral, so it can never pair this device. */
    PERIPHERAL_UNSUPPORTED,

    /** The BLE advertiser was rejected by the OS (e.g. too many advertisers already active). */
    ADVERTISE_FAILED,

    /** The device connected but the secure handshake did not complete in time. */
    HANDSHAKE_TIMEOUT,

    /** The secure handshake ran but authentication was rejected. */
    AUTH_FAILED,

    /** Advertising has been running with nothing connecting -- the device is likely still paired to
     * another phone (e.g. the manufacturer's official app) and must be removed from it first. */
    BOUND_ELSEWHERE,
}
