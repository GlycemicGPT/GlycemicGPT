package com.glycemicgpt.mobile.presentation.alerts

import com.glycemicgpt.mobile.data.network.NetworkStatus
import com.glycemicgpt.mobile.service.AlertStreamState
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The banner-visibility rule (AC4): the ONLY non-degraded combination is backend reachable + SSE
 * stream connected. Every other combination means no new server alerts arrive, so the honest
 * banner must show.
 */
class AlertingDegradedTest {

    @Test
    fun `reachable and connected is the only golden combination`() {
        assertFalse(isAlertingDegraded(NetworkStatus.REACHABLE, AlertStreamState.CONNECTED))
    }

    @Test
    fun `stream not connected is degraded even while backend is reachable`() {
        assertTrue(isAlertingDegraded(NetworkStatus.REACHABLE, AlertStreamState.DISCONNECTED))
        assertTrue(isAlertingDegraded(NetworkStatus.REACHABLE, AlertStreamState.RECONNECTING))
    }

    @Test
    fun `backend unreachable is degraded even while the stream still reports connected`() {
        // The SSE read timeout is minutes long; NetworkMonitor notices an outage first. The banner
        // must not wait for the stream to time out.
        assertTrue(isAlertingDegraded(NetworkStatus.BACKEND_UNREACHABLE, AlertStreamState.CONNECTED))
    }

    @Test
    fun `device offline is always degraded`() {
        for (stream in AlertStreamState.entries) {
            assertTrue(isAlertingDegraded(NetworkStatus.OFFLINE, stream))
        }
    }
}
