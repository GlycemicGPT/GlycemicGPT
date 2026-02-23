package com.glycemicgpt.mobile.ble.protocol

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class Crc16Test {

    @Test
    fun `empty data returns initial value FFFF`() {
        assertEquals(0xFFFF, Crc16.compute(byteArrayOf()))
    }

    @Test
    fun `known CRC-16 CCITT-FALSE for ASCII 123456789`() {
        // Standard test vector: "123456789" => 0x29B1
        val data = "123456789".toByteArray(Charsets.US_ASCII)
        assertEquals(0x29B1, Crc16.compute(data))
    }

    @Test
    fun `single byte zero`() {
        val crc = Crc16.compute(byteArrayOf(0x00))
        // CRC-16/CCITT-FALSE of single 0x00 byte is 0xE1F0
        assertEquals(0xE1F0, crc)
    }

    @Test
    fun `toBytes produces little-endian byte pair`() {
        val bytes = Crc16.toBytes(0x29B1)
        assertArrayEquals(byteArrayOf(0xB1.toByte(), 0x29), bytes)
    }

    @Test
    fun `offset and length parameters work correctly`() {
        val data = byteArrayOf(0xFF.toByte(), 0x31, 0x32, 0x33, 0xFF.toByte())
        val fullCrc = Crc16.compute("123".toByteArray(Charsets.US_ASCII))
        val subCrc = Crc16.compute(data, 1, 3)
        assertEquals(fullCrc, subCrc)
    }
}
