package com.glycemicgpt.mobile.data.network

import android.content.Context
import io.mockk.mockk
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Unit tests for the pure reachability logic. [NetworkMonitor.start] (which touches
 * ConnectivityManager) is never called, so a relaxed Context mock is enough — construction does no
 * framework work, by design.
 */
class NetworkMonitorTest {

    private fun monitor() = NetworkMonitor(mockk<Context>(relaxed = true))

    @Test
    fun `starts optimistic - online, reachable, no timestamp`() {
        val m = monitor()
        assertTrue(m.deviceOnline.value)
        assertTrue(m.backendReachable.value)
        assertNull(m.lastSuccessfulResponseAtMs.value)
        assertEquals(NetworkStatus.REACHABLE, m.status.value)
    }

    @Test
    fun `a single failure does not flip to unreachable`() {
        val m = monitor()
        m.recordBackendFailure()
        assertTrue(m.backendReachable.value)
        assertEquals(NetworkStatus.REACHABLE, m.status.value)
    }

    @Test
    fun `reaching the failure threshold flips to backend unreachable`() {
        val m = monitor()
        repeat(NetworkMonitor.FAILURE_THRESHOLD) { m.recordBackendFailure() }
        assertFalse(m.backendReachable.value)
        assertEquals(NetworkStatus.BACKEND_UNREACHABLE, m.status.value)
    }

    @Test
    fun `a success resets reachability and records a timestamp`() {
        val m = monitor()
        repeat(NetworkMonitor.FAILURE_THRESHOLD) { m.recordBackendFailure() }
        assertEquals(NetworkStatus.BACKEND_UNREACHABLE, m.status.value)

        m.recordBackendSuccess()
        assertTrue(m.backendReachable.value)
        assertEquals(NetworkStatus.REACHABLE, m.status.value)
        assertNotNull(m.lastSuccessfulResponseAtMs.value)
    }

    @Test
    fun `a success resets the consecutive-failure counter`() {
        val m = monitor()
        // One below the threshold, then a success, then one more failure: must NOT be unreachable
        // because the counter reset — otherwise a slow drip of unrelated failures would trip it.
        repeat(NetworkMonitor.FAILURE_THRESHOLD - 1) { m.recordBackendFailure() }
        m.recordBackendSuccess()
        m.recordBackendFailure()
        assertTrue(m.backendReachable.value)
        assertEquals(NetworkStatus.REACHABLE, m.status.value)
    }

    @Test
    fun `going offline reports OFFLINE and takes precedence over backend reachability`() {
        val m = monitor()
        m.setDeviceOnline(false)
        assertEquals(NetworkStatus.OFFLINE, m.status.value)
    }

    @Test
    fun `offline takes precedence even when the backend is also unreachable`() {
        val m = monitor()
        repeat(NetworkMonitor.FAILURE_THRESHOLD) { m.recordBackendFailure() }
        m.setDeviceOnline(false)
        assertEquals(NetworkStatus.OFFLINE, m.status.value)
    }

    @Test
    fun `coming back online with a reachable backend returns to REACHABLE`() {
        val m = monitor()
        m.setDeviceOnline(false)
        assertEquals(NetworkStatus.OFFLINE, m.status.value)
        m.setDeviceOnline(true)
        assertEquals(NetworkStatus.REACHABLE, m.status.value)
    }

    @Test
    fun `coming back online while the backend is still unreachable reports BACKEND_UNREACHABLE`() {
        val m = monitor()
        repeat(NetworkMonitor.FAILURE_THRESHOLD) { m.recordBackendFailure() }
        m.setDeviceOnline(false)
        assertEquals(NetworkStatus.OFFLINE, m.status.value)
        m.setDeviceOnline(true)
        assertEquals(NetworkStatus.BACKEND_UNREACHABLE, m.status.value)
    }
}
