package com.glycemicgpt.mobile.ble.protocol

/**
 * Encodes outbound messages into chunked BLE packets and reassembles inbound
 * packets into complete messages, following the Tandem BLE packet format.
 *
 * Packet layout (outbound):
 *   byte 0   : opcode
 *   byte 1   : transaction ID
 *   byte 2   : cargo length
 *   bytes 3+ : cargo
 *   trailer  : 2-byte CRC16 (little-endian)
 *
 * Each BLE write is a chunk:
 *   byte 0 : packets remaining in lower nibble (upper nibble = 0)
 *   byte 1 : transaction ID
 *   bytes 2+ : chunk payload
 */
object Packetize {

    /** Encode a message into BLE-writable chunks. */
    fun encode(opcode: Int, txId: Int, cargo: ByteArray, chunkSize: Int): List<ByteArray> {
        require(cargo.size <= 255) { "Cargo size ${cargo.size} exceeds max 255 bytes" }

        // Build the raw message bytes
        val raw = ByteArray(3 + cargo.size + 2)
        raw[0] = opcode.toByte()
        raw[1] = txId.toByte()
        raw[2] = cargo.size.toByte()
        cargo.copyInto(raw, 3)

        // CRC over opcode + txId + length + cargo (little-endian output)
        val crc = Crc16.compute(raw, 0, 3 + cargo.size)
        val crcBytes = Crc16.toBytes(crc)
        crcBytes.copyInto(raw, 3 + cargo.size)

        // Split into chunks (payload portion per chunk = chunkSize - 2 for header)
        val payloadPerChunk = chunkSize - 2
        val totalChunks = (raw.size + payloadPerChunk - 1) / payloadPerChunk
        val chunks = mutableListOf<ByteArray>()
        var offset = 0
        var chunkIndex = 0

        while (offset < raw.size) {
            val remaining = raw.size - offset
            val thisChunkPayload = minOf(remaining, payloadPerChunk)
            val packetsRemaining = totalChunks - chunkIndex - 1

            val chunk = ByteArray(2 + thisChunkPayload)
            // Remaining count goes in the LOWER nibble (Tandem protocol)
            chunk[0] = (packetsRemaining and 0x0F).toByte()
            chunk[1] = txId.toByte()
            raw.copyInto(chunk, 2, offset, offset + thisChunkPayload)

            chunks.add(chunk)
            offset += thisChunkPayload
            chunkIndex++
        }

        return chunks
    }

    /**
     * Parse the header of a reassembled raw message.
     * Returns Triple(opcode, txId, cargo) or null if invalid.
     */
    fun parseHeader(raw: ByteArray): Triple<Int, Int, ByteArray>? {
        if (raw.size < 5) return null // minimum: opcode + txId + length + 2 CRC
        val opcode = raw[0].toInt() and 0xFF
        val txId = raw[1].toInt() and 0xFF
        val cargoLen = raw[2].toInt() and 0xFF
        if (raw.size < 3 + cargoLen + 2) return null

        // Verify CRC (little-endian: low byte first, high byte second)
        val expectedCrc = Crc16.compute(raw, 0, 3 + cargoLen)
        val actualCrc = (raw[3 + cargoLen].toInt() and 0xFF) or
            ((raw[3 + cargoLen + 1].toInt() and 0xFF) shl 8)
        if (expectedCrc != actualCrc) return null

        val cargo = raw.copyOfRange(3, 3 + cargoLen)
        return Triple(opcode, txId, cargo)
    }
}
