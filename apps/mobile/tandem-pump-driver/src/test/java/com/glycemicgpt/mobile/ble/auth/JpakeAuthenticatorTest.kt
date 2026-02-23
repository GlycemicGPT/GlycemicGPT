package com.glycemicgpt.mobile.ble.auth

import com.glycemicgpt.mobile.ble.crypto.EcJpake
import com.glycemicgpt.mobile.ble.crypto.Hkdf
import com.glycemicgpt.mobile.ble.crypto.HmacSha256Util
import com.glycemicgpt.mobile.ble.protocol.Packetize
import com.glycemicgpt.mobile.ble.protocol.TandemProtocol
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.security.SecureRandom

/**
 * Integration test for JpakeAuthenticator that simulates a full JPAKE
 * handshake between a client (our app) and a simulated server (pump).
 */
class JpakeAuthenticatorTest {

    private lateinit var authenticator: JpakeAuthenticator

    @Before
    fun setUp() {
        authenticator = JpakeAuthenticator()
    }

    @Test
    fun `initial state is IDLE`() {
        assertEquals(JpakeAuthenticator.JpakeStep.IDLE, authenticator.step.value)
    }

    @Test
    fun `reset returns to IDLE`() {
        // Trigger some state change first
        authenticator.buildJpake1aRequest("123456", 0)
        assertEquals(JpakeAuthenticator.JpakeStep.ROUND_1A_SENT, authenticator.step.value)

        authenticator.reset()
        assertEquals(JpakeAuthenticator.JpakeStep.IDLE, authenticator.step.value)
    }

    @Test
    fun `buildJpake1aRequest produces valid chunks`() {
        val chunks = authenticator.buildJpake1aRequest("123456", 0)
        assertTrue("Should produce at least one chunk", chunks.isNotEmpty())
        assertEquals(JpakeAuthenticator.JpakeStep.ROUND_1A_SENT, authenticator.step.value)
    }

    @Test
    fun `processJpake1aResponse fails with too-short cargo`() {
        authenticator.buildJpake1aRequest("123456", 0)
        assertFalse(authenticator.processJpake1aResponse(ByteArray(10)))
        assertEquals(JpakeAuthenticator.JpakeStep.FAILED, authenticator.step.value)
    }

    @Test
    fun `processJpake1aResponse fails in wrong state`() {
        // Don't send 1a first
        assertFalse(authenticator.processJpake1aResponse(ByteArray(167)))
        assertEquals(JpakeAuthenticator.JpakeStep.FAILED, authenticator.step.value)
    }

    @Test
    fun `full JPAKE handshake with simulated server`() {
        val pairingCode = "123456"
        val codeBytes = pairingCode.toByteArray(Charsets.US_ASCII)

        // Create a server-side EcJpake to simulate the pump
        val serverJpake = EcJpake(EcJpake.Role.SERVER, codeBytes)

        // -- Step 1a: Client sends round 1 part A --
        val chunks1a = authenticator.buildJpake1aRequest(pairingCode, 0)
        assertTrue(chunks1a.isNotEmpty())
        assertEquals(JpakeAuthenticator.JpakeStep.ROUND_1A_SENT, authenticator.step.value)

        // Decode client chunks to get the raw cargo
        val raw1a = reassembleChunks(chunks1a)
        val parsed1a = Packetize.parseHeader(raw1a)!!
        assertEquals(TandemProtocol.OPCODE_JPAKE_1A_REQ, parsed1a.first)
        val clientCargo1a = parsed1a.third
        val clientChallenge1a = clientCargo1a.copyOfRange(2, 167) // Skip appInstanceId

        // Server generates its round 1
        val serverRound1 = serverJpake.getRound1()
        val serverChallenge1a = serverRound1.copyOfRange(0, 165)

        // Build server response for 1a
        val serverCargo1a = buildServerCargo(serverChallenge1a)
        assertTrue(authenticator.processJpake1aResponse(serverCargo1a))
        assertEquals(JpakeAuthenticator.JpakeStep.ROUND_1A_RECEIVED, authenticator.step.value)

        // -- Step 1b: Client sends round 1 part B --
        val chunks1b = authenticator.buildJpake1bRequest(1)
        assertTrue(chunks1b.isNotEmpty())
        assertEquals(JpakeAuthenticator.JpakeStep.ROUND_1B_SENT, authenticator.step.value)

        // Decode and extract client challenge 1b
        val raw1b = reassembleChunks(chunks1b)
        val parsed1b = Packetize.parseHeader(raw1b)!!
        assertEquals(TandemProtocol.OPCODE_JPAKE_1B_REQ, parsed1b.first)

        val serverChallenge1b = serverRound1.copyOfRange(165, 330)
        val serverCargo1b = buildServerCargo(serverChallenge1b)
        assertTrue(authenticator.processJpake1bResponse(serverCargo1b))
        assertEquals(JpakeAuthenticator.JpakeStep.ROUND_1B_RECEIVED, authenticator.step.value)

        // Server reads client's full round 1
        // We need the full client round 1 data (both parts)
        val fullClientRound1 = clientChallenge1a + parsed1b.third.copyOfRange(2, 167)
        serverJpake.readRound1(fullClientRound1)

        // -- Step 2: Client sends round 2 --
        val chunks2 = authenticator.buildJpake2Request(2)
        assertTrue(chunks2.isNotEmpty())
        assertEquals(JpakeAuthenticator.JpakeStep.ROUND_2_SENT, authenticator.step.value)

        // Decode client round 2
        val raw2 = reassembleChunks(chunks2)
        val parsed2 = Packetize.parseHeader(raw2)!!
        assertEquals(TandemProtocol.OPCODE_JPAKE_2_REQ, parsed2.first)
        val clientRound2Data = parsed2.third.copyOfRange(2, parsed2.third.size)

        // Server generates round 2 and reads client round 2
        val serverRound2 = serverJpake.getRound2()
        serverJpake.readRound2(clientRound2Data)

        // Build server response for round 2: appInstanceId(2) + serverRound2
        val serverCargo2 = ByteArray(2 + serverRound2.size)
        serverCargo2[0] = 1; serverCargo2[1] = 0 // appInstanceId = 1 LE
        serverRound2.copyInto(serverCargo2, 2)
        assertTrue(authenticator.processJpake2Response(serverCargo2))
        assertEquals(JpakeAuthenticator.JpakeStep.ROUND_2_RECEIVED, authenticator.step.value)

        // -- Step 3: Session key derivation --
        val chunks3 = authenticator.buildJpake3Request(3)
        assertTrue(chunks3.isNotEmpty())
        assertEquals(JpakeAuthenticator.JpakeStep.CONFIRM_3_SENT, authenticator.step.value)

        // Server derives secret
        val serverDerivedSecret = serverJpake.deriveSecret()
        val serverNonce3 = ByteArray(8).also { SecureRandom().nextBytes(it) }

        // Server response: appInstanceId(2) + nonce(8) + reserved(8)
        val serverCargo3 = ByteArray(18)
        serverCargo3[0] = 1; serverCargo3[1] = 0
        serverNonce3.copyInto(serverCargo3, 2)
        assertTrue(authenticator.processJpake3Response(serverCargo3))
        assertEquals(JpakeAuthenticator.JpakeStep.CONFIRM_3_RECEIVED, authenticator.step.value)

        // -- Step 4: Key confirmation --
        val chunks4 = authenticator.buildJpake4Request(4)
        assertTrue(chunks4.isNotEmpty())
        assertEquals(JpakeAuthenticator.JpakeStep.CONFIRM_4_SENT, authenticator.step.value)

        // Decode client key confirmation and verify the client's HMAC from server's perspective
        val raw4 = reassembleChunks(chunks4)
        val parsed4 = Packetize.parseHeader(raw4)!!
        assertEquals(TandemProtocol.OPCODE_JPAKE_4_KEY_CONFIRM_REQ, parsed4.first)

        val clientCargo4 = parsed4.third
        val clientNonce4 = clientCargo4.copyOfRange(2, 10)
        val clientHashDigest = clientCargo4.copyOfRange(18, 50)

        // Server verifies client's HMAC (same key derivation, client's nonce as data)
        val hkdfKey = Hkdf.build(serverNonce3, serverDerivedSecret)
        val expectedClientHash = HmacSha256Util.hmacSha256(clientNonce4, hkdfKey)
        assertTrue(
            "Server should accept client's key confirmation HMAC",
            clientHashDigest.contentEquals(expectedClientHash),
        )

        // Server computes its own HMAC for the response
        val serverNonce4 = ByteArray(8).also { SecureRandom().nextBytes(it) }
        val serverHashDigest = HmacSha256Util.hmacSha256(serverNonce4, hkdfKey)

        // Server response: appInstanceId(2) + nonce(8) + reserved(8) + hashDigest(32)
        val serverCargo4 = ByteArray(50)
        serverCargo4[0] = 1; serverCargo4[1] = 0
        serverNonce4.copyInto(serverCargo4, 2)
        // reserved bytes 10-17 are already zero
        serverHashDigest.copyInto(serverCargo4, 18)

        assertTrue(authenticator.processJpake4Response(serverCargo4))
        assertEquals(JpakeAuthenticator.JpakeStep.COMPLETE, authenticator.step.value)
    }

    // -- Helper methods --

    private fun buildServerCargo(challenge: ByteArray): ByteArray {
        val cargo = ByteArray(2 + challenge.size)
        cargo[0] = 1; cargo[1] = 0 // appInstanceId = 1 LE
        challenge.copyInto(cargo, 2)
        return cargo
    }

    private fun reassembleChunks(chunks: List<ByteArray>): ByteArray {
        val assembler = com.glycemicgpt.mobile.ble.protocol.PacketAssembler()
        for (chunk in chunks) {
            assembler.feed(chunk)
        }
        return assembler.assemble()
    }
}
