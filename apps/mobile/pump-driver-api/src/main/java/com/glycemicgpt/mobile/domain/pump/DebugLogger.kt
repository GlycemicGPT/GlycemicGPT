package com.glycemicgpt.mobile.domain.pump

/**
 * Abstraction for BLE packet debug logging.
 *
 * Provides a simplified logging API that doesn't expose internal
 * debug store types. Implementations in the app module translate
 * these calls to the concrete BleDebugStore.
 *
 * **Security:** Implementations must ensure that raw packet data
 * (cargoHex, parsedValue) is only retained in debug/development builds
 * and is never persisted to unencrypted storage. These fields may contain
 * sensitive medical data (glucose readings, insulin doses, device identifiers).
 */
interface DebugLogger {

    /** Packet direction for debug logging. */
    enum class Direction { TX, RX }

    fun logPacket(
        direction: Direction,
        opcode: Int,
        opcodeName: String,
        txId: Int,
        cargoHex: String,
        cargoSize: Int,
        parsedValue: String? = null,
        error: String? = null,
    )

    fun updateLastPacket(
        opcode: Int,
        direction: Direction,
        parsedValue: String? = null,
        error: String? = null,
    )
}
