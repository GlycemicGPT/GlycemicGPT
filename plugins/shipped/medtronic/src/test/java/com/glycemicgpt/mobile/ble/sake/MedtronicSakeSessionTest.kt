/*
 * Tests for the GlycemicGPT MedtronicSakeSession wrapper. The vendored OpenMinimed JavaSake
 * internals are proven byte-for-byte by the in-package org.openminimed.sake.* suite; this exercises
 * the transport-agnostic wrapper on top of them, including the captured 780G trace driven through
 * the wrapper's onPumpWrite() flow.
 *
 * The SAKE test vectors (firmware-extracted pump key DB, captured 780G handshake messages, and a
 * synthetic matched key-DB pair) are shared, published-upstream OpenMinimed protocol constants --
 * not session secrets and not unique per device. See medtronic-ble-reverse-engineering.md Sec. 12.
 */
package com.glycemicgpt.mobile.ble.sake

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import org.openminimed.sake.DeviceType
import org.openminimed.sake.KeyDatabase
import org.openminimed.sake.MacFailureException
import org.openminimed.sake.RngSource
import org.openminimed.sake.SakeClient
import org.openminimed.sake.Session

class MedtronicSakeSessionTest {

    @Test
    fun `wake-up frame is 20 zero bytes`() {
        val session = MedtronicSakeSession(pumpKeyDb())
        assertArrayEquals(ByteArray(Session.MESSAGE_SIZE), session.newWakeUpFrame())
    }

    @Test
    fun `captured 780G trace drives the wrapper handshake to completion`() {
        // Replay the random fields the phone chose in the original capture so the server re-emits
        // the same bytes: msg0 filler (18 B), server key material (8 B), server nonce (4 B).
        val capturedRng = QueuedRng(
            MESSAGES[0].copyOfRange(2, 20),
            MESSAGES[2].copyOfRange(8, 16),
            MESSAGES[2].copyOfRange(16, 20),
        )
        val session = MedtronicSakeSession(pumpKeyDb(), capturedRng)

        // The wake-up frame is NOT fed into the handshake -- only the pump's writes are.
        val msg0 = session.onPumpWrite(ByteArray(Session.MESSAGE_SIZE))
        assertArrayEquals(MESSAGES[0], msg0)
        assertEquals(1, session.stage)

        val msg2 = session.onPumpWrite(MESSAGES[1])
        assertArrayEquals(MESSAGES[2], msg2)
        assertEquals(3, session.stage)

        // The msg4 encrypted permit (first 16 bytes) must match the capture; only the pad-dependent
        // trailer differs (reproducing it needs package-private access, asserted by SakeServerTest).
        val msg4 = session.onPumpWrite(MESSAGES[3])!!
        assertEquals(5, session.stage)
        assertArrayEquals(MESSAGES[4].copyOfRange(0, 16), msg4.copyOfRange(0, 16))

        val done = session.onPumpWrite(MESSAGES[5])
        assertNull(done)
        assertEquals(MedtronicSakeSession.HANDSHAKE_COMPLETE_STAGE, session.stage)
        assertTrue(session.isComplete)
    }

    @Test
    fun `two-sided handshake completes and the derived cipher is decodable by the peer`() {
        val server = MedtronicSakeSession(KeyDatabase.fromBytes(hex(CUSTOM_SERVER_KEYDB_HEX)))
        val client = SakeClient(
            KeyDatabase.fromBytes(hex(CUSTOM_CLIENT_KEYDB_HEX)),
            DeviceType.INSULIN_PUMP,
        )

        val msg0 = server.onPumpWrite(ByteArray(Session.MESSAGE_SIZE))
        val msg1 = client.handshake(msg0)
        val msg2 = server.onPumpWrite(msg1)
        val msg3 = client.handshake(msg2)
        val msg4 = server.onPumpWrite(msg3)
        val msg5 = client.handshake(msg4)
        assertNull(server.onPumpWrite(msg5))

        assertTrue(server.isComplete)
        assertEquals(6, client.stage)

        // Outbound: encryptForPump uses the server-direction cipher; the peer decodes it with its
        // own server_crypt. A successful round-trip proves both sides derived the same session key.
        val outbound = "read-only".toByteArray()
        val encrypted = server.encryptForPump(outbound)
        assertFalse(encrypted.contentEquals(outbound))
        assertArrayEquals(outbound, client.session().serverCrypt().decrypt(encrypted))

        // Inbound: the pump (client) encrypts with its client_crypt; decryptFromPump must decode it
        // with the matching client-direction cipher (proves the inbound direction binding).
        val inbound = "from-pump".toByteArray()
        val pumpFrame = client.session().clientCrypt().encrypt(inbound)
        assertArrayEquals(inbound, server.decryptFromPump(pumpFrame))
    }

    @Test
    fun `cipher methods reject use before the handshake completes`() {
        val session = MedtronicSakeSession(pumpKeyDb())
        assertThrows(IllegalStateException::class.java) { session.encryptForPump(ByteArray(4)) }
        assertThrows(IllegalStateException::class.java) { session.decryptFromPump(ByteArray(4)) }
    }

    @Test
    fun `a tampered permit message fails authentication`() {
        // Drive the captured trace deterministically so the UNtampered MESSAGES[5] would
        // authenticate -- isolating the flipped byte as the sole cause of the failure (otherwise a
        // random RNG derives a different session key and msg5 would fail for the wrong reason).
        val capturedRng = QueuedRng(
            MESSAGES[0].copyOfRange(2, 20),
            MESSAGES[2].copyOfRange(8, 16),
            MESSAGES[2].copyOfRange(16, 20),
        )
        val session = MedtronicSakeSession(pumpKeyDb(), capturedRng)
        session.onPumpWrite(ByteArray(Session.MESSAGE_SIZE))
        session.onPumpWrite(MESSAGES[1])
        session.onPumpWrite(MESSAGES[3])
        val tamperedMsg5 = MESSAGES[5].clone().also { it[0] = (it[0].toInt() xor 0x01).toByte() }
        assertThrows(MacFailureException::class.java) { session.onPumpWrite(tamperedMsg5) }
    }

    private fun pumpKeyDb() = KeyDatabase.fromBytes(hex(PUMP_KEYDB_HEX))

    /** Deterministic [RngSource] that returns pre-seeded byte arrays in order. */
    private class QueuedRng(vararg chunks: ByteArray) : RngSource {
        private val queue = ArrayDeque(chunks.toList())
        override fun nextBytes(n: Int): ByteArray {
            val next = queue.removeFirst()
            require(next.size == n) { "Requested $n bytes but queued chunk is ${next.size}" }
            return next
        }
    }

    private companion object {
        /** Insulin-pump key database recovered from real 780G firmware (OpenMinimed, public). */
        const val PUMP_KEYDB_HEX =
            "f75995e70401011bc1bf7cbf36fa1e2367d795ff09211903da6afbe986b650f1" +
                "4179c0e6852e0ce393781078ffc6f51919e2eaefbde69b8eca21e41ab59b881a" +
                "0bea0286ea91dc7582a86a714e1737f558f0d66dc1895c"

        /** The six 20-byte handshake messages, in wire order, from a real 780G pairing capture. */
        val MESSAGES = arrayOf(
            hex("0401e2f09017a98f9f01cc56492fbacd4576e92b"), // msg0 server -> pump
            hex("42060e9f344e9312016ee8854d357f659b6b00ba"), // msg1 pump -> server
            hex("fdeeb13d04c3f18d272630ebeabe7c3a4d4d27b9"), // msg2 server -> pump
            hex("c02cec4ffb99affcb553a10fa6c55bb13d9fbacf"), // msg3 pump -> server
            hex("157d8e90214418a0e3d5f0517eebf4a82e00c02e"), // msg4 server -> pump
            hex("9b36f393b296fa84a757809859fc84a5c300d59b"), // msg5 pump -> server
        )

        /** Server-side (MOBILE_APPLICATION) half of the matched synthetic two-sided test pair. */
        const val CUSTOM_SERVER_KEYDB_HEX =
            "b079cdc504010144455249564154494f4e5f5f5f4b4559484e4453484b455f41" +
                "5554485f4b455950484f4e455f5045524d49545f454e4350484f4e455f5045" +
                "524d49545f4d4143ad14ad2780437db892d5650567d491b9"

        /** Client-side (INSULIN_PUMP) half of the matched synthetic two-sided test pair. */
        const val CUSTOM_CLIENT_KEYDB_HEX =
            "db8c1f2801010444455249564154494f4e5f5f5f4b4559484e4453484b455f41" +
                "5554485f4b455950554d505f5045524d49545f454e435250554d505f504552" +
                "4d49545f434d4143f2f8dbbb51563d4fa98fdaff0042a432"

        fun hex(s: String): ByteArray {
            require(s.length % 2 == 0) { "Hex string has odd length" }
            return ByteArray(s.length / 2) { i ->
                s.substring(2 * i, 2 * i + 2).toInt(16).toByte()
            }
        }
    }
}
