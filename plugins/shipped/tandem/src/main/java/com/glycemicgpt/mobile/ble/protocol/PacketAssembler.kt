package com.glycemicgpt.mobile.ble.protocol

/**
 * Reassembles multi-packet BLE notifications into a single raw message.
 *
 * Each incoming BLE notification has:
 *   byte 0 : packets-remaining indicator (0 = last packet)
 *   byte 1 : transaction ID
 *   bytes 2+ : payload fragment
 */
class PacketAssembler {

    private val buffer = mutableListOf<Byte>()
    private var expectedTxId: Int? = null

    /** Feed a raw BLE notification. Returns true when the message is complete. */
    fun feed(notification: ByteArray): Boolean {
        if (notification.size < 2) return false

        val packetsRemaining = notification[0].toInt() and 0x0F
        val txId = notification[1].toInt() and 0xFF

        if (expectedTxId == null) {
            expectedTxId = txId
        } else if (txId != expectedTxId) {
            // Transaction ID mismatch -- reset
            reset()
            expectedTxId = txId
        }

        // Append payload (skip 2-byte header)
        for (i in 2 until notification.size) {
            buffer.add(notification[i])
        }

        return packetsRemaining == 0
    }

    /** Get the reassembled raw message bytes. Call after feed() returns true. */
    fun assemble(): ByteArray = buffer.toByteArray()

    /** Reset the assembler for a new message. */
    fun reset() {
        buffer.clear()
        expectedTxId = null
    }
}
