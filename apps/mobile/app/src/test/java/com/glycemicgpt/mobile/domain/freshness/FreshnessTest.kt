package com.glycemicgpt.mobile.domain.freshness

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class FreshnessTest {

    // -- classify() boundaries -------------------------------------------------

    @Test
    fun `classify is FRESH below the stale threshold`() {
        val t = FreshnessThresholds(staleAfterMs = 1000, tooStaleAfterMs = 2000)
        assertEquals(Freshness.FRESH, t.classify(0))
        assertEquals(Freshness.FRESH, t.classify(999))
    }

    @Test
    fun `classify is STALE exactly at and above the stale threshold`() {
        val t = FreshnessThresholds(staleAfterMs = 1000, tooStaleAfterMs = 2000)
        assertEquals(Freshness.STALE, t.classify(1000))
        assertEquals(Freshness.STALE, t.classify(1999))
    }

    @Test
    fun `classify is TOO_STALE exactly at and above the too-stale threshold`() {
        val t = FreshnessThresholds(staleAfterMs = 1000, tooStaleAfterMs = 2000)
        assertEquals(Freshness.TOO_STALE, t.classify(2000))
        assertEquals(Freshness.TOO_STALE, t.classify(10_000))
    }

    @Test
    fun `classify treats a negative age (clock skew) as FRESH`() {
        val t = FreshnessThresholds(staleAfterMs = 1000, tooStaleAfterMs = 2000)
        assertEquals(Freshness.FRESH, t.classify(-5000))
    }

    @Test
    fun `invalid thresholds are rejected`() {
        assertThrows(IllegalArgumentException::class.java) {
            FreshnessThresholds(staleAfterMs = 2000, tooStaleAfterMs = 1000)
        }
        assertThrows(IllegalArgumentException::class.java) {
            FreshnessThresholds(staleAfterMs = 0, tooStaleAfterMs = 1000)
        }
        assertThrows(IllegalArgumentException::class.java) {
            FreshnessThresholds(staleAfterMs = 1000, tooStaleAfterMs = 1000)
        }
    }

    // -- Per-source policy -----------------------------------------------------

    @Test
    fun `CGM policy flips stale at 6 minutes and too-stale at 15 minutes`() {
        val cgm = FreshnessPolicy.CGM
        assertEquals(Freshness.FRESH, cgm.classify(5 * 60_000L))
        assertEquals(Freshness.STALE, cgm.classify(6 * 60_000L))
        assertEquals(Freshness.STALE, cgm.classify(14 * 60_000L))
        assertEquals(Freshness.TOO_STALE, cgm.classify(15 * 60_000L))
    }

    @Test
    fun `PUMP policy is looser than CGM`() {
        val pump = FreshnessPolicy.PUMP
        assertEquals(Freshness.FRESH, pump.classify(14 * 60_000L))
        assertEquals(Freshness.STALE, pump.classify(15 * 60_000L))
        assertEquals(Freshness.TOO_STALE, pump.classify(60 * 60_000L))
    }

    @Test
    fun `debug fast policy compresses transitions into seconds`() {
        val fast = FreshnessPolicy.CGM_DEBUG_FAST
        assertEquals(Freshness.FRESH, fast.classify(10_000L))
        assertEquals(Freshness.STALE, fast.classify(20_000L))
        assertEquals(Freshness.TOO_STALE, fast.classify(45_000L))
    }

    // -- relativeAgeLabel ------------------------------------------------------

    @Test
    fun `relativeAgeLabel formats seconds, minutes, hours and days`() {
        assertEquals("just now", relativeAgeLabel(0))
        assertEquals("just now", relativeAgeLabel(59_000))
        assertEquals("1m ago", relativeAgeLabel(60_000))
        assertEquals("59m ago", relativeAgeLabel(59 * 60_000L))
        assertEquals("1h ago", relativeAgeLabel(60 * 60_000L))
        assertEquals("23h ago", relativeAgeLabel(23 * 60 * 60_000L))
        assertEquals("1d ago", relativeAgeLabel(24 * 60 * 60_000L))
    }
}
