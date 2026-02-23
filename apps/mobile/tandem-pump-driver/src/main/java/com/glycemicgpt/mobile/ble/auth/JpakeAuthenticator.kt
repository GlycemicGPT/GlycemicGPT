package com.glycemicgpt.mobile.ble.auth

import com.glycemicgpt.mobile.ble.crypto.EcJpake
import com.glycemicgpt.mobile.ble.crypto.Hkdf
import com.glycemicgpt.mobile.ble.crypto.HmacSha256Util
import com.glycemicgpt.mobile.ble.protocol.Packetize
import com.glycemicgpt.mobile.ble.protocol.TandemProtocol
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import timber.log.Timber
import java.security.SecureRandom
import javax.inject.Inject
import javax.inject.Singleton

/**
 * EC-JPAKE authenticator for Tandem pumps with firmware v7.7+.
 *
 * The 6-digit pairing code displayed on the pump is used as the shared secret
 * for the JPAKE (Password Authenticated Key Exchange by Juggling) protocol.
 *
 * The JPAKE handshake consists of 5 request/response pairs:
 *   1a. Jpake1aRequest (opcode 32): first half of client round 1
 *   1b. Jpake1bRequest (opcode 34): second half of client round 1
 *   2.  Jpake2Request (opcode 36): client round 2
 *   3.  Jpake3SessionKeyRequest (opcode 38): triggers session key derivation
 *   4.  Jpake4KeyConfirmationRequest (opcode 40): client nonce + HMAC for verification
 *
 * Protocol reference: pumpX2 (MIT licensed) by jwoglom.
 */
@Singleton
class JpakeAuthenticator @Inject constructor() {

    enum class JpakeStep {
        IDLE,
        ROUND_1A_SENT,
        ROUND_1A_RECEIVED,
        ROUND_1B_SENT,
        ROUND_1B_RECEIVED,
        ROUND_2_SENT,
        ROUND_2_RECEIVED,
        CONFIRM_3_SENT,
        CONFIRM_3_RECEIVED,
        CONFIRM_4_SENT,
        COMPLETE,
        FAILED,
    }

    private val _step = MutableStateFlow(JpakeStep.IDLE)
    val step: StateFlow<JpakeStep> = _step.asStateFlow()

    private var cli: EcJpake? = null
    private val rand = SecureRandom()

    private var clientRound1: ByteArray? = null
    private var serverRound1PartA: ByteArray? = null
    private var derivedSecret: ByteArray? = null
    private var serverNonce3: ByteArray? = null
    private var clientNonce4: ByteArray? = null

    private val appInstanceId = 1 // pumpX2 uses 1

    fun reset() {
        _step.value = JpakeStep.IDLE
        cli = null
        // Zero sensitive crypto material before releasing references
        clientRound1?.fill(0)
        clientRound1 = null
        serverRound1PartA?.fill(0)
        serverRound1PartA = null
        derivedSecret?.fill(0)
        derivedSecret = null
        serverNonce3?.fill(0)
        serverNonce3 = null
        clientNonce4?.fill(0)
        clientNonce4 = null
    }

    /**
     * Build the initial Jpake1aRequest to start authentication.
     * Returns encoded BLE chunks to write to the AUTHORIZATION characteristic.
     */
    fun buildJpake1aRequest(pairingCode: String, txId: Int): List<ByteArray> {
        val codeBytes = pairingCodeToBytes(pairingCode)
        cli = EcJpake(EcJpake.Role.CLIENT, codeBytes, rand)

        clientRound1 = cli!!.getRound1()
        val challenge = clientRound1!!.copyOfRange(0, 165)

        val cargo = buildJpakeCargo(challenge)
        _step.value = JpakeStep.ROUND_1A_SENT

        Timber.d("JPAKE: Sending 1a request (%d bytes cargo)", cargo.size)
        return Packetize.encode(TandemProtocol.OPCODE_JPAKE_1A_REQ, txId, cargo, TandemProtocol.CHUNK_SIZE_SHORT)
    }

    /**
     * Process Jpake1aResponse from the pump.
     * Returns true if successful, false if the response is invalid.
     */
    fun processJpake1aResponse(responseCargo: ByteArray): Boolean {
        if (_step.value != JpakeStep.ROUND_1A_SENT) {
            Timber.e("JPAKE: unexpected 1a response in step %s", _step.value)
            _step.value = JpakeStep.FAILED
            return false
        }
        if (responseCargo.size < 167) {
            Timber.e("JPAKE: 1a response too short: %d bytes", responseCargo.size)
            _step.value = JpakeStep.FAILED
            return false
        }
        // Store first half of server round 1 (bytes 2-166 = 165 bytes challenge)
        serverRound1PartA = responseCargo.copyOfRange(2, 167)
        _step.value = JpakeStep.ROUND_1A_RECEIVED
        Timber.d("JPAKE: Received 1a response")
        return true
    }

    /**
     * Build the Jpake1bRequest (second half of client round 1).
     */
    fun buildJpake1bRequest(txId: Int): List<ByteArray> {
        check(_step.value == JpakeStep.ROUND_1A_RECEIVED) { "Invalid state: ${_step.value}" }

        val challenge = clientRound1!!.copyOfRange(165, 330)
        val cargo = buildJpakeCargo(challenge)
        _step.value = JpakeStep.ROUND_1B_SENT

        Timber.d("JPAKE: Sending 1b request (%d bytes cargo)", cargo.size)
        return Packetize.encode(TandemProtocol.OPCODE_JPAKE_1B_REQ, txId, cargo, TandemProtocol.CHUNK_SIZE_SHORT)
    }

    /**
     * Process Jpake1bResponse from the pump.
     * This completes round 1 -- we now have the full server round 1 data.
     */
    fun processJpake1bResponse(responseCargo: ByteArray): Boolean {
        if (_step.value != JpakeStep.ROUND_1B_SENT) {
            Timber.e("JPAKE: unexpected 1b response in step %s", _step.value)
            _step.value = JpakeStep.FAILED
            return false
        }
        if (responseCargo.size < 167) {
            Timber.e("JPAKE: 1b response too short: %d bytes", responseCargo.size)
            _step.value = JpakeStep.FAILED
            return false
        }
        // Combine both halves of server round 1
        val serverRound1PartB = responseCargo.copyOfRange(2, 167)
        val fullServerRound1 = serverRound1PartA!! + serverRound1PartB

        try {
            cli!!.readRound1(fullServerRound1)
        } catch (e: Exception) {
            Timber.e(e, "JPAKE: Failed to process server round 1")
            _step.value = JpakeStep.FAILED
            return false
        }

        _step.value = JpakeStep.ROUND_1B_RECEIVED
        Timber.d("JPAKE: Round 1 complete")
        return true
    }

    /**
     * Build the Jpake2Request (client round 2).
     */
    fun buildJpake2Request(txId: Int): List<ByteArray> {
        check(_step.value == JpakeStep.ROUND_1B_RECEIVED) { "Invalid state: ${_step.value}" }

        val clientRound2: ByteArray
        try {
            clientRound2 = cli!!.getRound2()
        } catch (e: Exception) {
            Timber.e(e, "JPAKE: Failed to generate round 2")
            _step.value = JpakeStep.FAILED
            return emptyList()
        }

        val challenge = clientRound2.copyOfRange(0, 165)
        val cargo = buildJpakeCargo(challenge)
        _step.value = JpakeStep.ROUND_2_SENT

        Timber.d("JPAKE: Sending round 2 request (%d bytes cargo)", cargo.size)
        return Packetize.encode(TandemProtocol.OPCODE_JPAKE_2_REQ, txId, cargo, TandemProtocol.CHUNK_SIZE_SHORT)
    }

    /**
     * Process Jpake2Response from the pump and derive the shared secret.
     */
    fun processJpake2Response(responseCargo: ByteArray): Boolean {
        if (_step.value != JpakeStep.ROUND_2_SENT) {
            Timber.e("JPAKE: unexpected round 2 response in step %s", _step.value)
            _step.value = JpakeStep.FAILED
            return false
        }
        if (responseCargo.size < 2) {
            Timber.e("JPAKE: round 2 response too short: %d bytes", responseCargo.size)
            _step.value = JpakeStep.FAILED
            return false
        }

        // Server round 2 data (skip 2-byte appInstanceId)
        val serverRound2 = responseCargo.copyOfRange(2, responseCargo.size)

        try {
            cli!!.readRound2(serverRound2)
        } catch (e: Exception) {
            Timber.e(e, "JPAKE: Failed to process server round 2")
            _step.value = JpakeStep.FAILED
            return false
        }

        _step.value = JpakeStep.ROUND_2_RECEIVED
        Timber.d("JPAKE: Round 2 complete")
        return true
    }

    /**
     * Build the Jpake3SessionKeyRequest (triggers session key derivation).
     * Used after a full bootstrap (rounds 1a, 1b, 2 complete).
     */
    fun buildJpake3Request(txId: Int): List<ByteArray> {
        check(_step.value == JpakeStep.ROUND_2_RECEIVED) { "Invalid state: ${_step.value}" }

        // Derive the shared secret
        try {
            derivedSecret = cli!!.deriveSecret()
        } catch (e: Exception) {
            Timber.e(e, "JPAKE: Failed to derive secret")
            _step.value = JpakeStep.FAILED
            return emptyList()
        }

        // Cargo is just the challengeParam (appInstanceId as 2-byte LE)
        val cargo = ByteArray(2)
        putShortLE(cargo, 0, appInstanceId)
        _step.value = JpakeStep.CONFIRM_3_SENT

        Timber.d("JPAKE: Sending session key request, derived secret computed")
        return Packetize.encode(TandemProtocol.OPCODE_JPAKE_3_SESSION_KEY_REQ, txId, cargo, TandemProtocol.CHUNK_SIZE_SHORT)
    }

    /**
     * Start JPAKE in CONFIRMATION mode (reconnect).
     *
     * Uses a previously derived secret from a successful bootstrap to skip
     * rounds 1a, 1b, and 2 entirely. Only rounds 3 (session key) and 4
     * (key confirmation) are performed, reducing the handshake from 5 to 2
     * round trips.
     *
     * The pump accepts this because the derived secret proves the client
     * previously completed a full JPAKE handshake with the correct pairing code.
     * The pump does not need to be in pairing mode for confirmation.
     */
    fun buildJpake3RequestFromDerivedSecret(
        savedDerivedSecret: ByteArray,
        txId: Int,
    ): List<ByteArray> {
        derivedSecret = savedDerivedSecret.copyOf()
        // No EcJpake instance needed -- we already have the derived secret.
        // Jump directly to round 3: session key request.
        val cargo = ByteArray(2)
        putShortLE(cargo, 0, appInstanceId)
        _step.value = JpakeStep.CONFIRM_3_SENT

        Timber.d("JPAKE CONFIRM: Sending session key request (skipped rounds 1-2)")
        return Packetize.encode(
            TandemProtocol.OPCODE_JPAKE_3_SESSION_KEY_REQ,
            txId, cargo, TandemProtocol.CHUNK_SIZE_SHORT,
        )
    }

    /**
     * Process Jpake3SessionKeyResponse from the pump (server nonce).
     */
    fun processJpake3Response(responseCargo: ByteArray): Boolean {
        if (_step.value != JpakeStep.CONFIRM_3_SENT) {
            Timber.e("JPAKE: unexpected session key response in step %s", _step.value)
            _step.value = JpakeStep.FAILED
            return false
        }
        if (responseCargo.size < 18) {
            Timber.e("JPAKE: session key response too short: %d bytes", responseCargo.size)
            _step.value = JpakeStep.FAILED
            return false
        }

        // Parse: appInstanceId(2) + deviceKeyNonce(8) + deviceKeyReserved(8)
        serverNonce3 = responseCargo.copyOfRange(2, 10)

        _step.value = JpakeStep.CONFIRM_3_RECEIVED
        Timber.d("JPAKE: Received server nonce")
        return true
    }

    /**
     * Build the Jpake4KeyConfirmationRequest (client nonce + HMAC).
     */
    fun buildJpake4Request(txId: Int): List<ByteArray> {
        check(_step.value == JpakeStep.CONFIRM_3_RECEIVED) { "Invalid state: ${_step.value}" }

        clientNonce4 = ByteArray(8).also { rand.nextBytes(it) }
        val hkdfKey = Hkdf.build(serverNonce3!!, derivedSecret!!)
        val hashDigest = HmacSha256Util.hmacSha256(clientNonce4!!, hkdfKey)

        // Cargo: appInstanceId(2) + nonce(8) + reserved(8) + hashDigest(32)
        val reserved = ByteArray(8)
        val cargo = ByteArray(50)
        putShortLE(cargo, 0, appInstanceId)
        clientNonce4!!.copyInto(cargo, 2)
        reserved.copyInto(cargo, 10)
        hashDigest.copyInto(cargo, 18)

        _step.value = JpakeStep.CONFIRM_4_SENT

        Timber.d("JPAKE: Sending key confirmation request")
        return Packetize.encode(TandemProtocol.OPCODE_JPAKE_4_KEY_CONFIRM_REQ, txId, cargo, TandemProtocol.CHUNK_SIZE_SHORT)
    }

    /**
     * Process Jpake4KeyConfirmationResponse from the pump.
     * Verifies the server's HMAC to complete authentication.
     * Returns true if authentication succeeded.
     */
    fun processJpake4Response(responseCargo: ByteArray): Boolean {
        if (_step.value != JpakeStep.CONFIRM_4_SENT) {
            Timber.e("JPAKE: unexpected key confirmation response in step %s", _step.value)
            _step.value = JpakeStep.FAILED
            return false
        }
        if (responseCargo.size < 50) {
            Timber.e("JPAKE: key confirmation response too short: %d bytes", responseCargo.size)
            _step.value = JpakeStep.FAILED
            return false
        }

        // Parse: appInstanceId(2) + nonce(8) + reserved(8) + hashDigest(32)
        val serverNonce4 = responseCargo.copyOfRange(2, 10)
        val serverHashDigest = responseCargo.copyOfRange(18, 50)

        // Verify: compute expected HMAC and compare
        val hkdfKey = Hkdf.build(serverNonce3!!, derivedSecret!!)
        val expectedHashDigest = HmacSha256Util.hmacSha256(serverNonce4, hkdfKey)

        val valid = serverHashDigest.contentEquals(expectedHashDigest)
        if (valid) {
            _step.value = JpakeStep.COMPLETE
            Timber.d("JPAKE: Authentication COMPLETE -- key confirmation verified")
        } else {
            _step.value = JpakeStep.FAILED
            Timber.e("JPAKE: Key confirmation FAILED -- HMAC mismatch")
        }
        return valid
    }

    /** Get the derived secret for persistence (returns a copy, or null if not yet computed). */
    fun getDerivedSecret(): ByteArray? = derivedSecret?.copyOf()

    /** Get the server nonce from round 3 for persistence (returns a copy, or null). */
    fun getServerNonce(): ByteArray? = serverNonce3?.copyOf()

    // -- Helper methods -------------------------------------------------------

    /**
     * Build JPAKE cargo: appInstanceId(2 LE) + challenge(165).
     */
    private fun buildJpakeCargo(challenge: ByteArray): ByteArray {
        val cargo = ByteArray(2 + challenge.size)
        putShortLE(cargo, 0, appInstanceId)
        challenge.copyInto(cargo, 2)
        return cargo
    }

    /**
     * Convert pairing code string to ASCII bytes matching pumpX2's charCode().
     */
    private fun pairingCodeToBytes(code: String): ByteArray {
        return code.toByteArray(Charsets.US_ASCII)
    }

    private fun putShortLE(buf: ByteArray, offset: Int, value: Int) {
        buf[offset] = (value and 0xFF).toByte()
        buf[offset + 1] = ((value shr 8) and 0xFF).toByte()
    }
}
