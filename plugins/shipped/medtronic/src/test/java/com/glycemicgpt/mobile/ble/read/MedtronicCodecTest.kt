/*
 * Tests for MedtronicCodec: little-endian decode, IEEE-11073 SFLOAT (medfloat16), and the E2E-CRC.
 * Expected values are cross-checked against OpenMinimed value_converter.py / parse_utils.py.
 */
package com.glycemicgpt.mobile.ble.read

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MedtronicCodecTest {

    @Test
    fun `little-endian decode`() {
        assertEquals(0x1234, MedtronicCodec.readUIntLe(byteArrayOf(0x34, 0x12), 0, 2))
        assertEquals(0x00F9, MedtronicCodec.readUIntLe(byteArrayOf(0xF9.toByte(), 0x00), 0, 2))
        assertEquals(0x019000, MedtronicCodec.readUIntLe(byteArrayOf(0x00, 0x90.toByte(), 0x01), 0, 3))
    }

    @Test
    fun `medfloat16 integer glucose has exponent zero`() {
        assertEquals(249.0, MedtronicCodec.decodeMedFloat16(0x00F9), 1e-9)
    }

    @Test
    fun `medfloat16 trend uses a negative exponent`() {
        // 0xe074: exponent nibble 0xe -> -2, mantissa 0x074 = 116 -> 1.16 mg/dL/min.
        assertEquals(1.16, MedtronicCodec.decodeMedFloat16(0xE074), 1e-9)
        // 0xe010: exponent -2, mantissa 16 -> 0.16 mg/dL/min.
        assertEquals(0.16, MedtronicCodec.decodeMedFloat16(0xE010), 1e-9)
    }

    @Test
    fun `medfloat16 sign-extends a negative mantissa`() {
        // 0x0f9c: exponent 0, mantissa 0xf9c has bit 11 set -> 3996 - 4096 = -100.
        assertEquals(-100.0, MedtronicCodec.decodeMedFloat16(0x0F9C), 1e-9)
    }

    @Test
    fun `medfloat16 reserved codes decode to non-finite sentinels`() {
        assertTrue(MedtronicCodec.decodeMedFloat16(0x07FF).isNaN()) // NaN
        assertTrue(MedtronicCodec.decodeMedFloat16(0x0800).isNaN()) // NRes
        assertTrue(MedtronicCodec.decodeMedFloat16(0x0801).isNaN()) // Reserved
        assertEquals(Double.POSITIVE_INFINITY, MedtronicCodec.decodeMedFloat16(0x07FE), 0.0)
        assertEquals(Double.NEGATIVE_INFINITY, MedtronicCodec.decodeMedFloat16(0x0802), 0.0)
    }

    @Test
    fun `e2e crc validates an upstream-captured packet`() {
        // value_converter.py __main__ asserts check_crc(...) is true for this vector.
        assertTrue(MedtronicCodec.checkE2eCrc(hex("ea07031c0a1f2a80ff0873")))
    }

    @Test
    fun `e2e crc validates the captured CGM measurement vector`() {
        assertTrue(MedtronicCodec.checkE2eCrc(hex("0ec3f900f40b000074e00a00e0f1")))
    }

    @Test
    fun `e2e crc rejects a corrupted packet`() {
        val tampered = hex("0ec3f900f40b000074e00a00e0f1").also { it[2] = (it[2] + 1).toByte() }
        assertFalse(MedtronicCodec.checkE2eCrc(tampered))
    }
}
