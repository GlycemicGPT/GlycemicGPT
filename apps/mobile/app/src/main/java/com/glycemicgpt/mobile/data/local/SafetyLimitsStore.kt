package com.glycemicgpt.mobile.data.local

import android.content.Context
import android.content.SharedPreferences
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Persists the user's safety limits locally.
 *
 * Values are fetched from the backend on connect and cached here.
 * The mobile app NEVER allows local override of safety limits --
 * only [updateAll] from backend sync is permitted.
 */
@Singleton
class SafetyLimitsStore @Inject constructor(
    @ApplicationContext context: Context,
) {
    private val prefs: SharedPreferences =
        context.getSharedPreferences("safety_limits", Context.MODE_PRIVATE)

    val minGlucoseMgDl: Int
        get() = prefs.getInt(KEY_MIN_GLUCOSE, SafetyLimits.DEFAULT_MIN_GLUCOSE)

    val maxGlucoseMgDl: Int
        get() = prefs.getInt(KEY_MAX_GLUCOSE, SafetyLimits.DEFAULT_MAX_GLUCOSE)

    val maxBasalRateMilliunits: Int
        get() = prefs.getInt(KEY_MAX_BASAL, SafetyLimits.DEFAULT_MAX_BASAL_MILLIUNITS)

    val maxBolusDoseMilliunits: Int
        get() = prefs.getInt(KEY_MAX_BOLUS, SafetyLimits.DEFAULT_MAX_BOLUS_MILLIUNITS)

    /** Timestamp of the last successful fetch from the backend. */
    val lastFetchedMs: Long
        get() = prefs.getLong(KEY_LAST_FETCHED, 0L)

    /**
     * Atomically update all four limits plus the fetch timestamp in a
     * single SharedPreferences transaction. Only called from backend sync.
     */
    fun updateAll(min: Int, max: Int, basal: Int, bolus: Int) {
        // Clamp to absolute hardware bounds before persisting so all access
        // paths (including direct property reads) return safe values.
        val clamped = SafetyLimits.safeOf(min, max, basal, bolus)
        prefs.edit()
            .putInt(KEY_MIN_GLUCOSE, clamped.minGlucoseMgDl)
            .putInt(KEY_MAX_GLUCOSE, clamped.maxGlucoseMgDl)
            .putInt(KEY_MAX_BASAL, clamped.maxBasalRateMilliunits)
            .putInt(KEY_MAX_BOLUS, clamped.maxBolusDoseMilliunits)
            .putLong(KEY_LAST_FETCHED, System.currentTimeMillis())
            .commit()
    }

    /** Clear all cached safety limits, resetting to defaults. Called on logout. */
    fun clear() {
        prefs.edit().clear().commit()
    }

    /** Returns true if the cached values are older than the given max age. */
    fun isStale(maxAgeMs: Long = STALE_THRESHOLD_MS): Boolean {
        val age = System.currentTimeMillis() - lastFetchedMs
        return age > maxAgeMs
    }

    /** Build SafetyLimits from cached values, clamped to absolute hardware bounds. */
    fun toSafetyLimits(): SafetyLimits = SafetyLimits.safeOf(
        minGlucoseMgDl = minGlucoseMgDl,
        maxGlucoseMgDl = maxGlucoseMgDl,
        maxBasalRateMilliunits = maxBasalRateMilliunits,
        maxBolusDoseMilliunits = maxBolusDoseMilliunits,
    )

    companion object {
        const val STALE_THRESHOLD_MS = 3_600_000L // 1 hour

        private const val KEY_MIN_GLUCOSE = "min_glucose"
        private const val KEY_MAX_GLUCOSE = "max_glucose"
        private const val KEY_MAX_BASAL = "max_basal"
        private const val KEY_MAX_BOLUS = "max_bolus"
        private const val KEY_LAST_FETCHED = "last_fetched_ms"
    }
}
