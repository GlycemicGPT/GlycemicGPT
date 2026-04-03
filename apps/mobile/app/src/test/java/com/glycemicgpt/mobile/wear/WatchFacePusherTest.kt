package com.glycemicgpt.mobile.wear

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WatchFacePusherTest {

    @Test
    fun `Result Success contains status and optional slotId`() {
        val result = WatchFacePusher.Result.Success(status = "installed", slotId = "slot-1")
        assertEquals("installed", result.status)
        assertEquals("slot-1", result.slotId)
    }

    @Test
    fun `Result Success allows null slotId`() {
        val result = WatchFacePusher.Result.Success(status = "sent", slotId = null)
        assertEquals("sent", result.status)
        assertEquals(null, result.slotId)
    }

    @Test
    fun `Result Error contains message`() {
        val result = WatchFacePusher.Result.Error("No watch connected")
        assertEquals("No watch connected", result.message)
    }

    @Test
    fun `Result sealed class covers all cases`() {
        val success: WatchFacePusher.Result = WatchFacePusher.Result.Success("ok", null)
        val error: WatchFacePusher.Result = WatchFacePusher.Result.Error("fail")
        assertTrue(success is WatchFacePusher.Result.Success)
        assertTrue(error is WatchFacePusher.Result.Error)
    }

    @Test
    fun `WATCHFACE_SHA256 is a valid 64-char hex string`() {
        val hash = WatchFacePusher.WATCHFACE_SHA256
        assertEquals(64, hash.length)
        assertTrue("SHA-256 must be lowercase hex", hash.matches(Regex("[0-9a-f]{64}")))
    }

}
