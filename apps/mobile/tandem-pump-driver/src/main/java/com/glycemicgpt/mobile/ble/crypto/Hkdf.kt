package com.glycemicgpt.mobile.ble.crypto

import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import kotlin.math.ceil

/**
 * Simplified HKDF (RFC 5869) implementation matching pumpX2's Hkdf class.
 *
 * Used in JPAKE key confirmation step to derive the session key
 * from the server nonce and the derived secret.
 */
object Hkdf {

    /** Build a 32-byte key from salt (nonce) and input keying material. */
    fun build(salt: ByteArray, ikm: ByteArray): ByteArray {
        val prk = extract(salt, ikm)
        return expand(prk, ByteArray(0), 32)
    }

    /** HKDF-Extract: PRK = HMAC-Hash(salt, IKM) per RFC 5869 section 2.2. */
    private fun extract(salt: ByteArray, ikm: ByteArray): ByteArray {
        val mac = initHmacSha256(salt)
        mac.update(ikm)
        val result = mac.doFinal()
        mac.reset()
        return result
    }

    /** HKDF-Expand: OKM = T(1) || T(2) || ... per RFC 5869 section 2.3. */
    private fun expand(prk: ByteArray, info: ByteArray, keyLength: Int): ByteArray {
        val mac = initHmacSha256(prk)
        var previousBlock = ByteArray(0)
        var resultKey = ByteArray(0)
        val numBlocks = ceil(keyLength / 32.0).toInt()

        for (blockIndex in 0 until numBlocks) {
            // T(i) = HMAC-Hash(PRK, T(i-1) || info || i) where i is a single octet
            val counter = byteArrayOf((blockIndex + 1).toByte())
            mac.update(previousBlock + info + counter)
            previousBlock = mac.doFinal()
            mac.reset()
            resultKey += previousBlock
        }
        return resultKey.copyOfRange(0, keyLength)
    }

    private fun initHmacSha256(key: ByteArray): Mac {
        val effectiveKey = if (key.isEmpty()) ByteArray(32) else key
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(effectiveKey, "HmacSHA256"))
        return mac
    }
}
