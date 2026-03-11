package com.glycemicgpt.weardevice.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WearDataContractTest {

    @Test
    fun `all paths start with glycemicgpt prefix`() {
        val paths = listOf(
            WearDataContract.IOB_PATH,
            WearDataContract.CGM_PATH,
            WearDataContract.ALERT_PATH,
            WearDataContract.CHAT_REQUEST_PATH,
            WearDataContract.CHAT_RESPONSE_PATH,
            WearDataContract.CHAT_ERROR_PATH,
            WearDataContract.ALERT_DISMISS_PATH,
            WearDataContract.WATCHFACE_PUSH_CHANNEL,
            WearDataContract.WATCHFACE_PUSH_STATUS_PATH,
        )
        paths.forEach { path ->
            assertTrue("Path '$path' should start with /glycemicgpt/", path.startsWith("/glycemicgpt/"))
        }
    }

    @Test
    fun `paths match phone-side contract values`() {
        assertEquals("/glycemicgpt/iob", WearDataContract.IOB_PATH)
        assertEquals("/glycemicgpt/cgm", WearDataContract.CGM_PATH)
        assertEquals("/glycemicgpt/alert", WearDataContract.ALERT_PATH)
        assertEquals("/glycemicgpt/chat/request", WearDataContract.CHAT_REQUEST_PATH)
        assertEquals("/glycemicgpt/chat/response", WearDataContract.CHAT_RESPONSE_PATH)
        assertEquals("/glycemicgpt/chat/error", WearDataContract.CHAT_ERROR_PATH)
    }

    @Test
    fun `alert dismiss path is defined`() {
        assertEquals("/glycemicgpt/alert/dismiss", WearDataContract.ALERT_DISMISS_PATH)
    }

    @Test
    fun `watch face push paths are defined`() {
        assertEquals("/glycemicgpt/watchface/push", WearDataContract.WATCHFACE_PUSH_CHANNEL)
        assertEquals("/glycemicgpt/watchface/status", WearDataContract.WATCHFACE_PUSH_STATUS_PATH)
    }

    @Test
    fun `capability names are defined`() {
        assertEquals("glycemicgpt_chat_relay", WearDataContract.CHAT_RELAY_CAPABILITY)
        assertEquals("glycemicgpt_watch_app", WearDataContract.WATCH_APP_CAPABILITY)
    }
}
