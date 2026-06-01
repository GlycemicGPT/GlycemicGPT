/*
 * AC2: confirm the inbound-cipher binding for post-handshake pump->phone traffic.
 *
 * B1 left `decryptFromPump = clientCrypt` verified only against a simulated peer and flagged that
 * PythonPumpConnector decrypts inbound pump traffic with `server_crypt` (sg_reader.py / socp.py).
 * This test resolves the apparent conflict at the cipher level: after a server-role handshake both
 * SeqCrypt instances share the same key and nonce and have rxSeq positioned at 2 (clientCrypt from
 * decrypting the pump's msg5; serverCrypt from SakeServer's explicit reset). Since SeqCrypt.decrypt
 * consumes only rxSeq, the two conventions recover identical plaintext -- so B1's binding is correct
 * and equivalent to upstream's. Live over-the-air confirmation against a real pump is TODO(48.A2).
 */
package com.glycemicgpt.mobile.ble.read

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.openminimed.sake.DeviceType
import org.openminimed.sake.KeyDatabase
import org.openminimed.sake.SakeClient
import org.openminimed.sake.SakeServer
import org.openminimed.sake.Session

class CipherDirectionConfirmationTest {

    @Test
    fun `inbound pump traffic decrypts identically with clientCrypt and serverCrypt`() {
        val server = SakeServer(KeyDatabase.fromBytes(hex(CUSTOM_SERVER_KEYDB_HEX)))
        val client = SakeClient(KeyDatabase.fromBytes(hex(CUSTOM_CLIENT_KEYDB_HEX)), DeviceType.INSULIN_PUMP)

        val msg0 = server.handshake(ByteArray(Session.MESSAGE_SIZE))
        val msg1 = client.handshake(msg0)
        val msg2 = server.handshake(msg1)
        val msg3 = client.handshake(msg2)
        val msg4 = server.handshake(msg3)
        val msg5 = client.handshake(msg4)
        assertNull(server.handshake(msg5))

        // The crux of the equivalence: both inbound ciphers are positioned at the same sequence.
        assertEquals(2L, server.session().clientCrypt().rxSeq)
        assertEquals(2L, server.session().serverCrypt().rxSeq)

        val payload = "from-pump-record".toByteArray()
        val frame = client.session().clientCrypt().encrypt(payload)

        // B1 (clientCrypt) and PythonPumpConnector (server_crypt) recover the same plaintext.
        assertArrayEquals(payload, server.session().clientCrypt().decrypt(frame.copyOf()))
        assertArrayEquals(payload, server.session().serverCrypt().decrypt(frame.copyOf()))
    }

    @Test
    fun `wrapper decryptFromPump recovers a genuinely pump-encrypted frame`() {
        val two = TwoSidedSession()
        val payload = "sg-record".toByteArray()
        assertArrayEquals(payload, two.server.decryptFromPump(two.pumpEncrypt(payload)))
    }
}
