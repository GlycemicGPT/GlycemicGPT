package com.glycemicgpt.mobile.data.local

import android.content.Context
import android.content.SharedPreferences
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Persists the user's analytics configuration locally.
 *
 * Values are fetched from the backend and cached here.
 * The day boundary hour controls when analytics periods (Insulin Summary,
 * Recent Boluses) start counting -- aligning with the pump's Delivery
 * Summary reset time.
 */
@Singleton
class AnalyticsSettingsStore @Inject constructor(
    @ApplicationContext context: Context,
) {
    private val prefs: SharedPreferences =
        context.getSharedPreferences("analytics_settings", Context.MODE_PRIVATE)

    val dayBoundaryHour: Int
        get() = prefs.getInt(KEY_DAY_BOUNDARY_HOUR, DEFAULT_DAY_BOUNDARY_HOUR)

    val lastFetchedMs: Long
        get() = prefs.getLong(KEY_LAST_FETCHED, 0L)

    fun updateAll(dayBoundaryHour: Int) {
        require(dayBoundaryHour in 0..23) { "dayBoundaryHour must be 0-23, was $dayBoundaryHour" }
        prefs.edit()
            .putInt(KEY_DAY_BOUNDARY_HOUR, dayBoundaryHour)
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
        const val DEFAULT_DAY_BOUNDARY_HOUR = 0
        const val STALE_THRESHOLD_MS = 900_000L // 15 minutes

        private const val KEY_DAY_BOUNDARY_HOUR = "day_boundary_hour"
        private const val KEY_LAST_FETCHED = "last_fetched_ms"
    }
}
