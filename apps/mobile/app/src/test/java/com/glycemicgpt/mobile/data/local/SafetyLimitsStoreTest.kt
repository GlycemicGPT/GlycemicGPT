package com.glycemicgpt.mobile.data.local

import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Tests for [SafetyLimitsStore] logic and [SafetyLimits.safeOf] clamping
 * used by the store's [toSafetyLimits] method.
 *
 * Uses an in-memory mirror to avoid Android SharedPreferences dependency.
 */
class SafetyLimitsStoreTest {

    @Test
    fun `defaults match SafetyLimits companion constants`() {
        val store = InMemorySafetyLimitsStore()
        assertEquals(SafetyLimits.DEFAULT_MIN_GLUCOSE, store.minGlucoseMgDl)
        assertEquals(SafetyLimits.DEFAULT_MAX_GLUCOSE, store.maxGlucoseMgDl)
        assertEquals(SafetyLimits.DEFAULT_MAX_BASAL_MILLIUNITS, store.maxBasalRateMilliunits)
        assertEquals(SafetyLimits.DEFAULT_MAX_BOLUS_MILLIUNITS, store.maxBolusDoseMilliunits)
    }

    @Test
    fun `updateAll persists all fields`() {
        val store = InMemorySafetyLimitsStore()
        store.updateAll(min = 40, max = 400, basal = 10000, bolus = 20000)
        assertEquals(40, store.minGlucoseMgDl)
        assertEquals(400, store.maxGlucoseMgDl)
        assertEquals(10000, store.maxBasalRateMilliunits)
        assertEquals(20000, store.maxBolusDoseMilliunits)
    }

    @Test
    fun `updateAll sets lastFetchedMs`() {
        val store = InMemorySafetyLimitsStore()
        assertEquals(0L, store.lastFetchedMs)
        store.updateAll(min = 20, max = 500, basal = 15000, bolus = 25000)
        assertTrue(store.lastFetchedMs > 0L)
    }

    @Test
    fun `isStale returns true when never fetched`() {
        val store = InMemorySafetyLimitsStore()
        assertTrue(store.isStale())
    }

    @Test
    fun `isStale returns false immediately after update`() {
        val store = InMemorySafetyLimitsStore()
        store.updateAll(min = 20, max = 500, basal = 15000, bolus = 25000)
        assertFalse(store.isStale())
    }

    @Test
    fun `isStale returns true when max age exceeded`() {
        val store = InMemorySafetyLimitsStore()
        store.updateAll(min = 20, max = 500, basal = 15000, bolus = 25000)
        // Force lastFetchedMs to a past time to guarantee staleness
        store.forceLastFetched(System.currentTimeMillis() - 5000L)
        assertTrue(store.isStale(maxAgeMs = 1000L))
    }

    @Test
    fun `toSafetyLimits returns defaults when not updated`() {
        val store = InMemorySafetyLimitsStore()
        val limits = store.toSafetyLimits()
        assertEquals(SafetyLimits.DEFAULT_MIN_GLUCOSE, limits.minGlucoseMgDl)
        assertEquals(SafetyLimits.DEFAULT_MAX_GLUCOSE, limits.maxGlucoseMgDl)
        assertEquals(SafetyLimits.DEFAULT_MAX_BASAL_MILLIUNITS, limits.maxBasalRateMilliunits)
        assertEquals(SafetyLimits.DEFAULT_MAX_BOLUS_MILLIUNITS, limits.maxBolusDoseMilliunits)
    }

    @Test
    fun `toSafetyLimits returns updated values`() {
        val store = InMemorySafetyLimitsStore()
        store.updateAll(min = 40, max = 400, basal = 10000, bolus = 20000)
        val limits = store.toSafetyLimits()
        assertEquals(40, limits.minGlucoseMgDl)
        assertEquals(400, limits.maxGlucoseMgDl)
        assertEquals(10000, limits.maxBasalRateMilliunits)
        assertEquals(20000, limits.maxBolusDoseMilliunits)
    }

    @Test
    fun `toSafetyLimits clamps out-of-range values`() {
        val store = InMemorySafetyLimitsStore()
        // Force invalid values directly (simulating corrupted prefs)
        store.forceValues(min = 5, max = 600, basal = 20000, bolus = 30000)
        val limits = store.toSafetyLimits()
        // Should be clamped to absolute bounds
        assertEquals(SafetyLimits.ABSOLUTE_MIN_GLUCOSE, limits.minGlucoseMgDl)
        assertEquals(SafetyLimits.ABSOLUTE_MAX_GLUCOSE, limits.maxGlucoseMgDl)
        assertEquals(SafetyLimits.ABSOLUTE_MAX_BASAL_MILLIUNITS, limits.maxBasalRateMilliunits)
        assertEquals(SafetyLimits.ABSOLUTE_MAX_BOLUS_MILLIUNITS, limits.maxBolusDoseMilliunits)
    }

    @Test
    fun `clear resets to defaults`() {
        val store = InMemorySafetyLimitsStore()
        store.updateAll(min = 40, max = 400, basal = 10000, bolus = 20000)
        store.clear()
        assertEquals(SafetyLimits.DEFAULT_MIN_GLUCOSE, store.minGlucoseMgDl)
        assertEquals(SafetyLimits.DEFAULT_MAX_GLUCOSE, store.maxGlucoseMgDl)
        assertEquals(SafetyLimits.DEFAULT_MAX_BASAL_MILLIUNITS, store.maxBasalRateMilliunits)
        assertEquals(SafetyLimits.DEFAULT_MAX_BOLUS_MILLIUNITS, store.maxBolusDoseMilliunits)
        assertEquals(0L, store.lastFetchedMs)
    }

    @Test
    fun `safeOf clamps inverted glucose ordering`() {
        // min > max should be clamped so min < max
        val limits = SafetyLimits.safeOf(minGlucoseMgDl = 450, maxGlucoseMgDl = 100)
        assertTrue(limits.minGlucoseMgDl < limits.maxGlucoseMgDl)
    }

    /**
     * In-memory mirror of [SafetyLimitsStore] for testing without Android
     * SharedPreferences. Mirrors the same storage/retrieval logic.
     */
    private class InMemorySafetyLimitsStore {
        private var _minGlucose: Int = SafetyLimits.DEFAULT_MIN_GLUCOSE
        private var _maxGlucose: Int = SafetyLimits.DEFAULT_MAX_GLUCOSE
        private var _maxBasal: Int = SafetyLimits.DEFAULT_MAX_BASAL_MILLIUNITS
        private var _maxBolus: Int = SafetyLimits.DEFAULT_MAX_BOLUS_MILLIUNITS
        var lastFetchedMs: Long = 0L
            private set

        fun forceLastFetched(ms: Long) {
            lastFetchedMs = ms
        }

        val minGlucoseMgDl: Int get() = _minGlucose
        val maxGlucoseMgDl: Int get() = _maxGlucose
        val maxBasalRateMilliunits: Int get() = _maxBasal
        val maxBolusDoseMilliunits: Int get() = _maxBolus

        fun updateAll(min: Int, max: Int, basal: Int, bolus: Int) {
            _minGlucose = min
            _maxGlucose = max
            _maxBasal = basal
            _maxBolus = bolus
            lastFetchedMs = System.currentTimeMillis()
        }

        fun forceValues(min: Int, max: Int, basal: Int, bolus: Int) {
            _minGlucose = min
            _maxGlucose = max
            _maxBasal = basal
            _maxBolus = bolus
        }

        fun clear() {
            _minGlucose = SafetyLimits.DEFAULT_MIN_GLUCOSE
            _maxGlucose = SafetyLimits.DEFAULT_MAX_GLUCOSE
            _maxBasal = SafetyLimits.DEFAULT_MAX_BASAL_MILLIUNITS
            _maxBolus = SafetyLimits.DEFAULT_MAX_BOLUS_MILLIUNITS
            lastFetchedMs = 0L
        }

        fun isStale(maxAgeMs: Long = SafetyLimitsStore.STALE_THRESHOLD_MS): Boolean {
            val age = System.currentTimeMillis() - lastFetchedMs
            return age > maxAgeMs
        }

        fun toSafetyLimits(): SafetyLimits = SafetyLimits.safeOf(
            minGlucoseMgDl = _minGlucose,
            maxGlucoseMgDl = _maxGlucose,
            maxBasalRateMilliunits = _maxBasal,
            maxBolusDoseMilliunits = _maxBolus,
        )
    }
}
