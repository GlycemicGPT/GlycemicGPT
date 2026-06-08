package com.glycemicgpt.mobile.ble.protocol

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class PduFramerTest {

    @Test
    fun `the 20-byte cap derives from the default 23-byte MTU`() {
        assertEquals(23, PduFramer.DEFAULT_MTU)
        assertEquals(3, PduFramer.ATT_HEADER_SIZE)
        assertEquals(20, PduFramer.MAX_PDU_SIZE)
    }

    @Test
    fun `a 20-byte SAKE-sized payload passes through as a single unfragmented chunk`() {
        val payload = ByteArray(20) { it.toByte() }
        val chunks = PduFramer.fragment(payload)
        assertEquals(1, chunks.size)
        assertArrayEquals(payload, chunks[0])
        // Returned chunk is a copy, not the caller's array.
        assertNotSame(payload, chunks[0])
    }

    @Test
    fun `an oversized payload fragments into chunks of at most 20 bytes`() {
        val payload = ByteArray(50) { it.toByte() }
        val chunks = PduFramer.fragment(payload)
        assertEquals(3, chunks.size) // 20 + 20 + 10
        assertTrue(chunks.all { it.size <= PduFramer.MAX_PDU_SIZE })
        assertEquals(20, chunks[0].size)
        assertEquals(20, chunks[1].size)
        assertEquals(10, chunks[2].size)
    }

    @Test
    fun `fragment then reassemble round-trips an oversized payload`() {
        val payload = ByteArray(101) { (it * 7).toByte() }
        assertArrayEquals(payload, PduFramer.reassemble(PduFramer.fragment(payload)))
    }

    @Test
    fun `fragment honors a smaller caller-supplied PDU size`() {
        val payload = ByteArray(10) { it.toByte() }
        val chunks = PduFramer.fragment(payload, maxPduSize = 4)
        assertEquals(3, chunks.size) // 4 + 4 + 2
        assertArrayEquals(payload, PduFramer.reassemble(chunks))
    }

    @Test
    fun `an empty payload yields a single empty chunk`() {
        val chunks = PduFramer.fragment(ByteArray(0))
        assertEquals(1, chunks.size)
        assertEquals(0, chunks[0].size)
        assertArrayEquals(ByteArray(0), PduFramer.reassemble(chunks))
    }

    @Test
    fun `fragment rejects a PDU size above the transport cap`() {
        assertThrows(IllegalArgumentException::class.java) {
            PduFramer.fragment(ByteArray(40), maxPduSize = 21)
        }
    }

    @Test
    fun `fragment rejects a non-positive PDU size`() {
        assertThrows(IllegalArgumentException::class.java) {
            PduFramer.fragment(ByteArray(40), maxPduSize = 0)
        }
    }
}
