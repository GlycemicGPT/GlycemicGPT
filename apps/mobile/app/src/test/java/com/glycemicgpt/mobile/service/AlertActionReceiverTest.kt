package com.glycemicgpt.mobile.service

import org.junit.Assert.assertEquals
import org.junit.Test

class AlertActionReceiverTest {

    @Test
    fun `action constants are stable`() {
        assertEquals(
            "com.glycemicgpt.mobile.ACTION_ACKNOWLEDGE_ALERT",
            AlertActionReceiver.ACTION_ACKNOWLEDGE,
        )
    }

    @Test
    fun `extra key constants are stable`() {
        assertEquals("extra_server_id", AlertActionReceiver.EXTRA_SERVER_ID)
        assertEquals("extra_notification_id", AlertActionReceiver.EXTRA_NOTIFICATION_ID)
    }
}
