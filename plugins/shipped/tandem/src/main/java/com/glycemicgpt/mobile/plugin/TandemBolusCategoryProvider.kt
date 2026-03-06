package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.domain.plugin.capabilities.BolusCategoryProvider

/**
 * Tandem-specific bolus category provider.
 *
 * Maps Tandem pump bolus categories (derived from BLE source/type fields)
 * to the platform's standard category names used by [BolusCategory].
 */
class TandemBolusCategoryProvider : BolusCategoryProvider {

    override fun declaredCategories(): Set<String> = CATEGORIES

    override fun toPlatformCategory(pluginCategory: String): String? =
        CATEGORY_MAP[pluginCategory]

    companion object {
        const val CONTROL_IQ = "CONTROL_IQ"
        const val BG_FOOD = "BG_FOOD"
        const val BG_ONLY = "BG_ONLY"
        const val FOOD_ONLY = "FOOD_ONLY"
        const val OVERRIDE = "OVERRIDE"
        const val QUICK = "QUICK"
        const val UNKNOWN = "UNKNOWN"

        private val CATEGORIES = setOf(
            CONTROL_IQ, BG_FOOD, BG_ONLY, FOOD_ONLY, OVERRIDE, QUICK, UNKNOWN,
        )

        private val CATEGORY_MAP = mapOf(
            CONTROL_IQ to "AUTO_CORRECTION",
            BG_FOOD to "FOOD_AND_CORRECTION",
            BG_ONLY to "CORRECTION",
            FOOD_ONLY to "FOOD",
            OVERRIDE to "OVERRIDE",
            QUICK to "OTHER",
            UNKNOWN to "OTHER",
        )
    }
}
