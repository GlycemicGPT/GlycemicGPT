package com.glycemicgpt.mobile.domain.pump

import org.junit.Assert.assertEquals
import org.junit.Test

class HexUtilsTest {

    @Test
    fun `toSpacedHex formats low bytes correctly`() {
        val bytes = byteArrayOf(0x0a, 0x1b, 0x2c)
        assertEquals("0a 1b 2c", bytes.toSpacedHex())
    }

    @Test
    fun `toSpacedHex handles high bytes without sign extension`() {
        // Bytes >= 0x80 are negative as signed Kotlin Byte.
        // Must produce 2-char hex, not sign-extended "ffffffff..." values.
        val bytes = byteArrayOf(0xFF.toByte(), 0x80.toByte(), 0xAB.toByte())
        assertEquals("ff 80 ab", bytes.toSpacedHex())
    }

    @Test
    fun `toSpacedHex handles empty array`() {
        assertEquals("", byteArrayOf().toSpacedHex())
    }

    @Test
    fun `toSpacedHex handles single byte`() {
        assertEquals("00", byteArrayOf(0x00).toSpacedHex())
        assertEquals("ff", byteArrayOf(0xFF.toByte()).toSpacedHex())
    }
}
