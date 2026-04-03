package com.glycemicgpt.mobile.ble.protocol

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class PacketizeTest {

    @Test
    fun `encode produces single chunk for small message`() {
        val chunks = Packetize.encode(
            opcode = 0x10,
            txId = 1,
            cargo = byteArrayOf(0x01, 0x02),
            chunkSize = 40,
        )
        assertEquals(1, chunks.size)
        // First byte: packets remaining = 0 (lower nibble)
        assertEquals(0, chunks[0][0].toInt() and 0x0F)
        // Second byte: txId = 1
        assertEquals(1, chunks[0][1].toInt() and 0xFF)
    }

    @Test
    fun `encode and parseHeader round-trip`() {
        val opcode = 0x20
        val txId = 5
        val cargo = byteArrayOf(0xAA.toByte(), 0xBB.toByte(), 0xCC.toByte())

        val chunks = Packetize.encode(opcode, txId, cargo, 40)

        // Simulate receiving: strip chunk headers and reassemble
        val assembler = PacketAssembler()
        for (chunk in chunks) {
            assembler.feed(chunk)
        }
        val raw = assembler.assemble()

        val parsed = Packetize.parseHeader(raw)
        assertNotNull(parsed)
        assertEquals(opcode, parsed!!.first)
        assertEquals(txId, parsed.second)
        assertArrayEquals(cargo, parsed.third)
    }

    @Test
    fun `encode splits into multiple chunks with small chunk size`() {
        // 10 bytes cargo + 3 header + 2 CRC = 15 bytes raw
        // With chunkSize=6, payload per chunk = 4 bytes, need 4 chunks
        val cargo = ByteArray(10) { it.toByte() }
        val chunks = Packetize.encode(0x01, 0, cargo, 6)
        assertEquals(4, chunks.size)

        // Last chunk should have packets-remaining = 0 (lower nibble)
        val lastChunk = chunks.last()
        assertEquals(0, lastChunk[0].toInt() and 0x0F)

        // Verify packets-remaining counts down correctly: 3, 2, 1, 0
        for (i in chunks.indices) {
            val expected = chunks.size - i - 1
            val actual = chunks[i][0].toInt() and 0x0F
            assertEquals("Chunk $i packets-remaining", expected, actual)
        }
    }

    @Test
    fun `encode rejects cargo larger than 255 bytes`() {
        try {
            Packetize.encode(0x01, 0, ByteArray(256), 40)
            assert(false) { "Expected IllegalArgumentException" }
        } catch (e: IllegalArgumentException) {
            // Expected
        }
    }

    @Test
    fun `multi-chunk encode and parseHeader round-trip`() {
        val opcode = 0x10
        val txId = 3
        val cargo = ByteArray(30) { (it * 7).toByte() } // 30-byte cargo forces multi-chunk

        val chunks = Packetize.encode(opcode, txId, cargo, 18)
        assert(chunks.size > 1) { "Expected multiple chunks for 30-byte cargo with chunkSize=18" }

        // Reassemble through PacketAssembler
        val assembler = PacketAssembler()
        for (chunk in chunks) {
            assembler.feed(chunk)
        }
        val raw = assembler.assemble()

        val parsed = Packetize.parseHeader(raw)
        assertNotNull(parsed)
        assertEquals(opcode, parsed!!.first)
        assertEquals(txId, parsed.second)
        assertArrayEquals(cargo, parsed.third)
    }

    @Test
    fun `parseHeader returns null for too-short data`() {
        assertNull(Packetize.parseHeader(byteArrayOf(0x01, 0x02)))
    }

    @Test
    fun `parseHeader returns null for corrupted CRC`() {
        val opcode = 0x10
        val txId = 1
        val cargo = byteArrayOf(0x01)

        val chunks = Packetize.encode(opcode, txId, cargo, 40)
        val assembler = PacketAssembler()
        for (chunk in chunks) {
            assembler.feed(chunk)
        }
        val raw = assembler.assemble()

        // Corrupt the CRC (last byte)
        raw[raw.size - 1] = (raw[raw.size - 1].toInt() xor 0xFF).toByte()
        assertNull(Packetize.parseHeader(raw))
    }

    @Test
    fun `parseHeader returns null when cargo length exceeds data`() {
        // Build raw bytes with cargo length set too high
        val raw = byteArrayOf(0x10, 0x01, 0x0A, 0x01, 0x02) // claims 10 bytes cargo but only 2
        assertNull(Packetize.parseHeader(raw))
    }
}
