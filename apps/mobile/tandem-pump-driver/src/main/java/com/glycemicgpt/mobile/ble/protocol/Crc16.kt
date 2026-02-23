package com.glycemicgpt.mobile.ble.protocol

/**
 * CRC-16/CCITT-FALSE used by the Tandem BLE protocol for message integrity.
 */
object Crc16 {

    private const val POLYNOMIAL = 0x1021
    private const val INITIAL = 0xFFFF

    fun compute(data: ByteArray, offset: Int = 0, length: Int = data.size): Int {
        var crc = INITIAL
        for (i in offset until offset + length) {
            crc = crc xor ((data[i].toInt() and 0xFF) shl 8)
            for (bit in 0 until 8) {
                crc = if (crc and 0x8000 != 0) {
                    (crc shl 1) xor POLYNOMIAL
                } else {
                    crc shl 1
                }
                crc = crc and 0xFFFF
            }
        }
        return crc
    }

    /** Convert CRC to 2 bytes in little-endian order (matching Tandem protocol). */
    fun toBytes(crc: Int): ByteArray = byteArrayOf(
        (crc and 0xFF).toByte(),
        ((crc shr 8) and 0xFF).toByte(),
    )
}
