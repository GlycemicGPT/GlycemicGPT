package com.glycemicgpt.mobile.ble.connection

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder

class HistoryLogCargoTest {

    @Test
    fun `buildHistoryLogCargo encodes correct 5-byte format`() {
        val cargo = TandemBleDriver.buildHistoryLogCargo(startIndex = 1000, count = 20)
        assertEquals(5, cargo.size)

        val buf = ByteBuffer.wrap(cargo).order(ByteOrder.LITTLE_ENDIAN)
        assertEquals(1000, buf.int)
        assertEquals(20, cargo[4].toInt() and 0xFF)
    }

    @Test
    fun `buildHistoryLogCargo with sequence zero`() {
        val cargo = TandemBleDriver.buildHistoryLogCargo(startIndex = 0, count = 1)
        assertEquals(5, cargo.size)

        val buf = ByteBuffer.wrap(cargo).order(ByteOrder.LITTLE_ENDIAN)
        assertEquals(0, buf.int)
        assertEquals(1, cargo[4].toInt() and 0xFF)
    }

    @Test
    fun `buildHistoryLogCargo with large sequence number`() {
        val cargo = TandemBleDriver.buildHistoryLogCargo(startIndex = Int.MAX_VALUE, count = 10)
        assertEquals(5, cargo.size)

        val buf = ByteBuffer.wrap(cargo).order(ByteOrder.LITTLE_ENDIAN)
        assertEquals(Int.MAX_VALUE, buf.int)
        assertEquals(10, cargo[4].toInt() and 0xFF)
    }

    @Test
    fun `buildHistoryLogCargo clamps count to 255`() {
        val cargo = TandemBleDriver.buildHistoryLogCargo(startIndex = 100, count = 300)
        assertEquals(255, cargo[4].toInt() and 0xFF)
    }

    @Test
    fun `buildHistoryLogCargo clamps count minimum to 1`() {
        val cargo = TandemBleDriver.buildHistoryLogCargo(startIndex = 100, count = 0)
        assertEquals(1, cargo[4].toInt() and 0xFF)
    }

    @Test
    fun `buildHistoryLogCargo encodes little-endian sequence`() {
        // Sequence 0x04030201 should be stored as [01, 02, 03, 04] in LE
        val cargo = TandemBleDriver.buildHistoryLogCargo(startIndex = 0x04030201, count = 5)
        assertArrayEquals(byteArrayOf(0x01, 0x02, 0x03, 0x04, 0x05), cargo)
    }
}
