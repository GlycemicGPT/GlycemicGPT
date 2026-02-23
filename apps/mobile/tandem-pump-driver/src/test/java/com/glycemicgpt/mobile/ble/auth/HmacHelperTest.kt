package com.glycemicgpt.mobile.ble.auth

import org.junit.Assert.assertEquals
import org.junit.Test

class HmacHelperTest {

    @Test
    fun `hmacSha1 produces 20-byte digest`() {
        val key = "testkey".toByteArray()
        val data = "testdata".toByteArray()
        val result = HmacHelper.hmacSha1(key, data)
        assertEquals(20, result.size)
    }

    @Test
    fun `hmacSha1 produces known result for RFC 2202 test vector 1`() {
        // RFC 2202 Test Case 1:
        // Key = 0x0b repeated 20 times
        // Data = "Hi There"
        // HMAC-SHA-1 = b617318655057264e28bc0b6fb378c8ef146be00
        val key = ByteArray(20) { 0x0b }
        val data = "Hi There".toByteArray(Charsets.US_ASCII)
        val result = HmacHelper.hmacSha1(key, data)

        val expected = "b617318655057264e28bc0b6fb378c8ef146be00"
        val actual = result.joinToString("") { "%02x".format(it) }
        assertEquals(expected, actual)
    }

    @Test
    fun `buildChallengeResponse uses pairing code as key`() {
        val pairingCode = "ABCDEF1234567890"
        val challenge = byteArrayOf(0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08)

        val result = HmacHelper.buildChallengeResponse(pairingCode, challenge)
        assertEquals(20, result.size)

        // Verify it matches direct HMAC computation
        val expected = HmacHelper.hmacSha1(
            pairingCode.toByteArray(Charsets.US_ASCII),
            challenge,
        )
        assertEquals(expected.toList(), result.toList())
    }

    @Test
    fun `different pairing codes produce different results`() {
        val challenge = byteArrayOf(0x01, 0x02, 0x03)
        val result1 = HmacHelper.buildChallengeResponse("CODE1111111111111", challenge)
        val result2 = HmacHelper.buildChallengeResponse("CODE2222222222222", challenge)
        assert(result1.toList() != result2.toList())
    }
}
