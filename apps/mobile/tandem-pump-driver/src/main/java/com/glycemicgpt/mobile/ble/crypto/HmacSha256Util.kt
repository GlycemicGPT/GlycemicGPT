package com.glycemicgpt.mobile.ble.crypto

import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * HMAC-SHA256 utility matching pumpX2's HmacSha256 implementation.
 *
 * Note: pumpX2 applies a `mod255` byte transformation before HMAC, but that
 * function is a mathematical no-op: `(b + 256) & 255` always equals the
 * original unsigned byte value. We omit it here for clarity.
 */
object HmacSha256Util {

    fun hmacSha256(data: ByteArray, key: ByteArray): ByteArray {
        val secretKey = SecretKeySpec(key, "HmacSHA256")
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(secretKey)
        return mac.doFinal(data)
    }
}
