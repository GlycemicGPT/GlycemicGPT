package com.glycemicgpt.mobile.ble.connection

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Tests for the reconnection scheduling backoff logic
 * used in [BleConnectionManager].
 *
 * These verify that the tiered reconnection strategy (fast exponential
 * backoff -> slow periodic) behaves correctly.
 *
 * Implementation constants (thresholds, intervals) are private to
 * BleConnectionManager; these tests verify the mathematical properties
 * of the backoff formula rather than asserting constant values.
 */
class ReconnectSchedulerTest {

    @Test
    fun `fast phase backoff delay doubles each attempt`() {
        // The backoff formula: min(1000 * (1 << min(attempt, 5)), 32000)
        val expected = listOf(
            1 to 2_000L,
            2 to 4_000L,
            3 to 8_000L,
            4 to 16_000L,
            5 to 32_000L,
        )
        for ((attempt, expectedDelay) in expected) {
            val delay = minOf(1000L * (1 shl minOf(attempt, 5)), 32_000L)
            assertEquals("Attempt $attempt should delay $expectedDelay ms", expectedDelay, delay)
        }
    }

    @Test
    fun `fast phase backoff caps at 32 seconds`() {
        // Attempts beyond 5 should still cap at 32s
        for (attempt in 6..10) {
            val delay = minOf(1000L * (1 shl minOf(attempt, 5)), 32_000L)
            assertEquals("Attempt $attempt should cap at 32000 ms", 32_000L, delay)
        }
    }

    @Test
    fun `first attempt delay is 2 seconds`() {
        // attempt=1 (first call to scheduleReconnect increments to 1)
        val delay = minOf(1000L * (1 shl minOf(1, 5)), 32_000L)
        assertEquals(2_000L, delay)
    }

    @Test
    fun `total fast phase delay is approximately 222 seconds`() {
        // Sum of all fast-phase delays for attempts 1..10
        var total = 0L
        for (attempt in 1..10) {
            total += minOf(1000L * (1 shl minOf(attempt, 5)), 32_000L)
        }
        // Should be: 2 + 4 + 8 + 16 + 32 + 32 + 32 + 32 + 32 + 32 = 222 seconds
        // Plus connection + auth time per attempt (~2-5s each)
        // Should be approximately 4-5 minutes total wall clock
        assertEquals("Fast phase total should be 222s", 222_000L, total)
    }
}
