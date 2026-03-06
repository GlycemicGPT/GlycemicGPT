package com.glycemicgpt.mobile.data.local

import android.content.Context
import android.content.SharedPreferences
import com.glycemicgpt.mobile.data.remote.dto.DisplayLabelDto
import com.glycemicgpt.mobile.domain.model.BolusCategory
import dagger.hilt.android.qualifiers.ApplicationContext
import org.json.JSONObject
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Persists the user's analytics configuration locally.
 *
 * Values are fetched from the backend and cached here.
 * The day boundary hour controls when analytics periods (Insulin Summary,
 * Recent Boluses) start counting -- aligning with the pump's Delivery
 * Summary reset time.
 *
 * Category labels allow the user to customize how bolus categories are
 * displayed. Labels are stored as a JSON string mapping BolusCategory
 * names to display strings.
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

    val categoryLabels: Map<String, String>
        get() {
            val json = prefs.getString(KEY_CATEGORY_LABELS, null) ?: return emptyMap()
            return try {
                val obj = JSONObject(json)
                buildMap {
                    for (key in obj.keys()) {
                        put(key, obj.getString(key))
                    }
                }
            } catch (e: Exception) {
                Timber.w(e, "Failed to parse category labels JSON")
                emptyMap()
            }
        }

    fun labelFor(category: BolusCategory): String =
        categoryLabels[category.name] ?: category.displayName

    fun updateAll(dayBoundaryHour: Int, categoryLabels: Map<String, String>? = null) {
        require(dayBoundaryHour in 0..23) { "dayBoundaryHour must be 0-23, was $dayBoundaryHour" }
        prefs.edit()
            .putInt(KEY_DAY_BOUNDARY_HOUR, dayBoundaryHour)
            .putLong(KEY_LAST_FETCHED, System.currentTimeMillis())
            .also { editor ->
                if (categoryLabels != null) {
                    val json = JSONObject(categoryLabels).toString()
                    editor.putString(KEY_CATEGORY_LABELS, json)
                }
            }
            .apply()
    }

    fun updateCategoryLabels(labels: Map<String, String>) {
        val json = JSONObject(labels).toString()
        prefs.edit()
            .putString(KEY_CATEGORY_LABELS, json)
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
        private const val KEY_CATEGORY_LABELS = "category_labels"

        /**
         * Convert a list of [DisplayLabelDto] to a category labels map.
         * Only labels with a non-null computationRole are included.
         * Falls back to [fallback] if [displayLabels] is null or empty.
         */
        fun displayLabelsToMap(
            displayLabels: List<DisplayLabelDto>?,
            fallback: Map<String, String>?,
        ): Map<String, String>? {
            if (!displayLabels.isNullOrEmpty()) {
                return buildMap {
                    for (dl in displayLabels) {
                        val role = dl.computationRole ?: continue
                        put(role, dl.label)
                    }
                }
            }
            return fallback
        }
    }
}
