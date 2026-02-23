package com.glycemicgpt.mobile.ble.auth

import com.glycemicgpt.mobile.ble.protocol.Packetize
import com.glycemicgpt.mobile.ble.protocol.TandemProtocol
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import timber.log.Timber
import java.security.SecureRandom
import javax.inject.Inject

/**
 * Manages the Tandem BLE authentication handshake.
 *
 * Protocol (matching pumpX2 reference):
 * 1. Send CentralChallengeRequest: 2-byte LE appInstanceId + 8-byte random challenge
 * 2. Receive CentralChallengeResponse (30 bytes):
 *    - bytes 0-1: appInstanceId echo
 *    - bytes 2-21: centralChallengeHash (pump's HMAC of our challenge)
 *    - bytes 22-29: hmacKey (8 bytes we use for our response)
 * 3. Compute HMAC-SHA1(key=pairingCode, data=hmacKey)
 * 4. Send PumpChallengeRequest: 2-byte LE appInstanceId + 20-byte HMAC
 * 5. Receive PumpChallengeResponse (3 bytes):
 *    - bytes 0-1: appInstanceId echo
 *    - byte 2: 1=success, 0=failure
 *
 * The pairing code is the 6-digit code displayed on the pump screen.
 */
class TandemAuthenticator @Inject constructor() {

    private val _authState = MutableStateFlow(AuthState.IDLE)
    val authState: StateFlow<AuthState> = _authState.asStateFlow()

    private val random = SecureRandom()

    /** 16-bit app instance ID, serialized as 2 bytes little-endian. */
    private var appInstanceId: Int = 0
    private var pairingCode: String = ""

    /** Reset authenticator for a new attempt. */
    fun reset() {
        _authState.value = AuthState.IDLE
        appInstanceId = 0
        pairingCode = ""
    }

    /**
     * Build the initial CentralChallengeRequest payload.
     *
     * Cargo format (10 bytes):
     *   bytes 0-1: appInstanceId (16-bit LE)
     *   bytes 2-9: centralChallenge (8 random bytes)
     */
    fun buildCentralChallengeRequest(txId: Int): List<ByteArray> {
        appInstanceId = random.nextInt(0xFFFF)
        val challengeBytes = ByteArray(8).also { random.nextBytes(it) }

        val cargo = ByteArray(2 + challengeBytes.size) // 10 bytes
        putShortLE(cargo, 0, appInstanceId)
        challengeBytes.copyInto(cargo, 2)

        _authState.value = AuthState.CHALLENGE_SENT
        Timber.d("Auth: sending CentralChallengeRequest (txId=%d, appId=%d)", txId, appInstanceId)

        return Packetize.encode(
            TandemProtocol.OPCODE_CENTRAL_CHALLENGE_REQ,
            txId,
            cargo,
            TandemProtocol.CHUNK_SIZE_SHORT,
        )
    }

    /**
     * Process the CentralChallengeResponse from the pump.
     *
     * Response cargo (30 bytes):
     *   bytes 0-1:   appInstanceId echo (LE short)
     *   bytes 2-21:  centralChallengeHash (20 bytes, pump's HMAC of our challenge)
     *   bytes 22-29: hmacKey (8 bytes, used as data for our HMAC response)
     *
     * @param responseCargo The cargo bytes from the pump's response
     * @param code The pairing code entered by the user
     * @param txId Transaction ID for the outbound PumpChallengeRequest
     * @return BLE chunks for the PumpChallengeRequest, or null if state/format is invalid
     */
    fun processChallengeResponse(
        responseCargo: ByteArray,
        code: String,
        txId: Int,
    ): List<ByteArray>? {
        if (_authState.value != AuthState.CHALLENGE_SENT) {
            Timber.w("Auth: unexpected CentralChallengeResponse in state %s", _authState.value)
            return null
        }

        if (responseCargo.size < 30) {
            Timber.e(
                "Auth: CentralChallengeResponse cargo too short: %d bytes (expected 30)",
                responseCargo.size,
            )
            _authState.value = AuthState.FAILED
            return null
        }

        pairingCode = code

        // Extract the 8-byte HMAC key from bytes 22-29 of the response
        val hmacKey = responseCargo.copyOfRange(22, 30)
        val hmacResult = HmacHelper.buildChallengeResponse(pairingCode, hmacKey)

        _authState.value = AuthState.RESPONSE_SENT
        Timber.d("Auth: sending PumpChallengeRequest (txId=%d)", txId)

        // PumpChallengeRequest cargo = 2-byte LE appInstanceId + 20-byte HMAC
        val cargo = ByteArray(2 + hmacResult.size) // 22 bytes
        putShortLE(cargo, 0, appInstanceId)
        hmacResult.copyInto(cargo, 2)

        return Packetize.encode(
            TandemProtocol.OPCODE_PUMP_CHALLENGE_REQ,
            txId,
            cargo,
            TandemProtocol.CHUNK_SIZE_SHORT,
        )
    }

    /**
     * Process the PumpChallengeResponse confirming auth success/failure.
     *
     * Response cargo (3 bytes):
     *   bytes 0-1: appInstanceId echo (LE short)
     *   byte 2:    1 = success, 0 = failure
     *
     * @param responseCargo Cargo bytes from the pump's response
     * @return true if authentication succeeded
     */
    fun processPumpChallengeResponse(responseCargo: ByteArray): Boolean {
        if (_authState.value != AuthState.RESPONSE_SENT) {
            Timber.w("Auth: unexpected PumpChallengeResponse in state %s", _authState.value)
            _authState.value = AuthState.FAILED
            return false
        }

        if (responseCargo.size < 3) {
            Timber.e(
                "Auth: PumpChallengeResponse cargo too short: %d bytes (expected 3)",
                responseCargo.size,
            )
            _authState.value = AuthState.FAILED
            return false
        }

        // Byte 2: 1 = authenticated, 0 = rejected
        val success = (responseCargo[2].toInt() and 0xFF) == 1
        _authState.value = if (success) AuthState.AUTHENTICATED else AuthState.FAILED

        Timber.d("Auth: PumpChallengeResponse success=%b (byte=%d)", success, responseCargo[2])
        return success
    }

    /** Write a 16-bit value in little-endian at the given offset. */
    private fun putShortLE(dst: ByteArray, offset: Int, value: Int) {
        dst[offset] = (value and 0xFF).toByte()
        dst[offset + 1] = ((value shr 8) and 0xFF).toByte()
    }
}
