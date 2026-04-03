package com.glycemicgpt.mobile.data.local

import android.content.Context
import android.content.SharedPreferences
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Persists pump profile summary data fetched from the backend.
 *
 * Caches DIA, max bolus, profile name, and segment count so the UI
 * can display pump profile info without requiring a network call.
 */
@Singleton
class PumpProfileStore @Inject constructor(
    @ApplicationContext context: Context,
) {
    private val prefs: SharedPreferences =
        context.getSharedPreferences("pump_profile", Context.MODE_PRIVATE)

    val profileName: String
        get() = prefs.getString(KEY_PROFILE_NAME, "") ?: ""

    val diaMinutes: Int
        get() = prefs.getInt(KEY_DIA_MINUTES, 0)

    val maxBolusUnits: Float
        get() = prefs.getFloat(KEY_MAX_BOLUS, 0f)

    val segmentCount: Int
        get() = prefs.getInt(KEY_SEGMENT_COUNT, 0)

    val lastFetchedMs: Long
        get() = prefs.getLong(KEY_LAST_FETCHED, 0L)

    val hasProfile: Boolean
        get() = profileName.isNotEmpty()

    fun updateAll(
        profileName: String,
        diaMinutes: Int,
        maxBolusUnits: Float,
        segmentCount: Int,
    ) {
        require(diaMinutes >= 0) { "diaMinutes must be non-negative, was $diaMinutes" }
        require(maxBolusUnits in 0f..MAX_BOLUS_UNITS_CAP) {
            "maxBolusUnits must be 0-$MAX_BOLUS_UNITS_CAP, was $maxBolusUnits"
        }
        prefs.edit()
            .putString(KEY_PROFILE_NAME, profileName)
            .putInt(KEY_DIA_MINUTES, diaMinutes)
            .putFloat(KEY_MAX_BOLUS, maxBolusUnits)
            .putInt(KEY_SEGMENT_COUNT, segmentCount)
            .putLong(KEY_LAST_FETCHED, System.currentTimeMillis())
            .apply()
    }

    fun clear() {
        prefs.edit().clear().apply()
    }

    fun isStale(maxAgeMs: Long = STALE_THRESHOLD_MS): Boolean {
        val age = System.currentTimeMillis() - lastFetchedMs
        return age > maxAgeMs
    }

    companion object {
        const val STALE_THRESHOLD_MS = 3_600_000L // 1 hour
        private const val MAX_BOLUS_UNITS_CAP = 25f // Tandem hardware max

        private const val KEY_PROFILE_NAME = "profile_name"
        private const val KEY_DIA_MINUTES = "dia_minutes"
        private const val KEY_MAX_BOLUS = "max_bolus"
        private const val KEY_SEGMENT_COUNT = "segment_count"
        private const val KEY_LAST_FETCHED = "last_fetched_ms"
    }
}
