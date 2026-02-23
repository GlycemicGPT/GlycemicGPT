package com.glycemicgpt.mobile.ble.auth

import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TandemAuthenticatorTest {

    private val authenticator = TandemAuthenticator()

    /** Build a valid 30-byte CentralChallengeResponse cargo. */
    private fun buildChallengeResponseCargo(hmacKey: ByteArray = ByteArray(8) { 0x42 }): ByteArray {
        val cargo = ByteArray(30)
        // Bytes 0-1: appInstanceId echo (LE short)
        cargo[0] = 0x01
        cargo[1] = 0x00
        // Bytes 2-21: centralChallengeHash (20 bytes, pump's HMAC)
        for (i in 2..21) cargo[i] = 0xAA.toByte()
        // Bytes 22-29: hmacKey (8 bytes)
        hmacKey.copyInto(cargo, 22)
        return cargo
    }

    /** Build a PumpChallengeResponse cargo: 2-byte appId + 1 success byte. */
    private fun buildPumpResponseCargo(success: Boolean): ByteArray {
        return byteArrayOf(0x01, 0x00, if (success) 1 else 0)
    }

    @Test
    fun `initial state is IDLE`() = runTest {
        assertEquals(AuthState.IDLE, authenticator.authState.first())
    }

    @Test
    fun `buildCentralChallengeRequest transitions to CHALLENGE_SENT`() = runTest {
        val chunks = authenticator.buildCentralChallengeRequest(txId = 1)
        assertTrue(chunks.isNotEmpty())
        assertEquals(AuthState.CHALLENGE_SENT, authenticator.authState.first())
    }

    @Test
    fun `processChallengeResponse returns null when not in CHALLENGE_SENT state`() {
        // Still in IDLE state
        val result = authenticator.processChallengeResponse(
            responseCargo = buildChallengeResponseCargo(),
            code = "123456",
            txId = 2,
        )
        assertNull(result)
    }

    @Test
    fun `processChallengeResponse returns null for cargo shorter than 30 bytes`() = runTest {
        authenticator.buildCentralChallengeRequest(txId = 1)
        val result = authenticator.processChallengeResponse(
            responseCargo = ByteArray(8) { 0x42 },
            code = "123456",
            txId = 2,
        )
        assertNull(result)
        assertEquals(AuthState.FAILED, authenticator.authState.first())
    }

    @Test
    fun `processChallengeResponse transitions to RESPONSE_SENT with valid 30-byte cargo`() = runTest {
        authenticator.buildCentralChallengeRequest(txId = 1)
        val chunks = authenticator.processChallengeResponse(
            responseCargo = buildChallengeResponseCargo(),
            code = "123456",
            txId = 2,
        )
        assertNotNull(chunks)
        assertTrue(chunks!!.isNotEmpty())
        assertEquals(AuthState.RESPONSE_SENT, authenticator.authState.first())
    }

    @Test
    fun `processPumpChallengeResponse returns false when not in RESPONSE_SENT state`() = runTest {
        val result = authenticator.processPumpChallengeResponse(buildPumpResponseCargo(true))
        assertFalse(result)
        assertEquals(AuthState.FAILED, authenticator.authState.first())
    }

    @Test
    fun `processPumpChallengeResponse succeeds when byte 2 is 1`() = runTest {
        authenticator.buildCentralChallengeRequest(txId = 1)
        authenticator.processChallengeResponse(
            responseCargo = buildChallengeResponseCargo(),
            code = "123456",
            txId = 2,
        )

        val success = authenticator.processPumpChallengeResponse(buildPumpResponseCargo(true))
        assertTrue(success)
        assertEquals(AuthState.AUTHENTICATED, authenticator.authState.first())
    }

    @Test
    fun `processPumpChallengeResponse fails when byte 2 is 0`() = runTest {
        authenticator.buildCentralChallengeRequest(txId = 1)
        authenticator.processChallengeResponse(
            responseCargo = buildChallengeResponseCargo(),
            code = "123456",
            txId = 2,
        )

        val success = authenticator.processPumpChallengeResponse(buildPumpResponseCargo(false))
        assertFalse(success)
        assertEquals(AuthState.FAILED, authenticator.authState.first())
    }

    @Test
    fun `processPumpChallengeResponse fails with cargo shorter than 3 bytes`() = runTest {
        authenticator.buildCentralChallengeRequest(txId = 1)
        authenticator.processChallengeResponse(
            responseCargo = buildChallengeResponseCargo(),
            code = "123456",
            txId = 2,
        )

        val success = authenticator.processPumpChallengeResponse(byteArrayOf(0x01, 0x00))
        assertFalse(success)
        assertEquals(AuthState.FAILED, authenticator.authState.first())
    }

    @Test
    fun `reset returns to IDLE state`() = runTest {
        authenticator.buildCentralChallengeRequest(txId = 1)
        assertEquals(AuthState.CHALLENGE_SENT, authenticator.authState.first())

        authenticator.reset()
        assertEquals(AuthState.IDLE, authenticator.authState.first())
    }
}
