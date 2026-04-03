package com.glycemicgpt.mobile.ble.protocol

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PacketAssemblerTest {

    @Test
    fun `single packet with zero remaining completes immediately`() {
        val assembler = PacketAssembler()
        // packets-remaining=0 (lower nibble), txId=1, payload=0xAA 0xBB
        val notification = byteArrayOf(0x00, 0x01, 0xAA.toByte(), 0xBB.toByte())
        assertTrue(assembler.feed(notification))
        assertArrayEquals(byteArrayOf(0xAA.toByte(), 0xBB.toByte()), assembler.assemble())
    }

    @Test
    fun `multi-packet assembly`() {
        val assembler = PacketAssembler()
        // First packet: packets-remaining=1 (0x01 in lower nibble), txId=5, payload=0x01 0x02
        assertFalse(assembler.feed(byteArrayOf(0x01, 0x05, 0x01, 0x02)))
        // Second packet: packets-remaining=0 (0x00), txId=5, payload=0x03 0x04
        assertTrue(assembler.feed(byteArrayOf(0x00, 0x05, 0x03, 0x04)))

        assertArrayEquals(byteArrayOf(0x01, 0x02, 0x03, 0x04), assembler.assemble())
    }

    @Test
    fun `txId mismatch resets buffer`() {
        val assembler = PacketAssembler()
        // First packet with txId=1, remaining=1 in lower nibble
        assembler.feed(byteArrayOf(0x01, 0x01, 0xAA.toByte()))
        // Second packet with different txId=2 (resets)
        assembler.feed(byteArrayOf(0x00, 0x02, 0xBB.toByte()))

        // Should only have the payload from the second txId
        assertArrayEquals(byteArrayOf(0xBB.toByte()), assembler.assemble())
    }

    @Test
    fun `too-short notification returns false`() {
        val assembler = PacketAssembler()
        assertFalse(assembler.feed(byteArrayOf(0x00)))
    }

    @Test
    fun `reset clears state`() {
        val assembler = PacketAssembler()
        assembler.feed(byteArrayOf(0x01, 0x01, 0xAA.toByte()))
        assembler.reset()

        // After reset, new packet with different txId should work without mismatch
        assertTrue(assembler.feed(byteArrayOf(0x00, 0x05, 0xBB.toByte())))
        assertArrayEquals(byteArrayOf(0xBB.toByte()), assembler.assemble())
    }
}
