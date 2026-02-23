package com.glycemicgpt.mobile.ble.auth

import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * HMAC-SHA1 helper for the Tandem legacy authentication handshake.
 *
 * The pump sends a challenge key; the client computes HMAC-SHA1
 * over it using the 16-character pairing code as the secret.
 */
object HmacHelper {

    private const val ALGORITHM = "HmacSHA1"

    /**
     * Compute HMAC-SHA1 over [data] using [key].
     * Returns 20-byte digest.
     */
    fun hmacSha1(key: ByteArray, data: ByteArray): ByteArray {
        val mac = Mac.getInstance(ALGORITHM)
        mac.init(SecretKeySpec(key, ALGORITHM))
        return mac.doFinal(data)
    }

    /**
     * Build the HMAC response for the Tandem auth challenge.
     *
     * @param pairingCode Pairing code from pump screen (ASCII bytes used as HMAC key)
     * @param challengeKey 8-byte HMAC key from bytes 22-29 of CentralChallengeResponse
     */
    fun buildChallengeResponse(pairingCode: String, challengeKey: ByteArray): ByteArray {
        val keyBytes = pairingCode.toByteArray(Charsets.US_ASCII)
        return hmacSha1(keyBytes, challengeKey)
    }
}
