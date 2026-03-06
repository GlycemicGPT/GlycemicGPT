package com.glycemicgpt.mobile.domain.compute

import com.glycemicgpt.mobile.domain.model.BolusCategory
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.plugin.capabilities.BolusCategoryProvider

/**
 * Resolves a [BolusEvent] to a platform-standard [BolusCategory].
 *
 * Uses the plugin's [BolusCategoryProvider] when available and the bolus has
 * a non-empty category field. Falls back to flag-based derivation for old data
 * (pre-migration, category="") or when no provider is available.
 */
object BolusCategoryMapper {

    /**
     * Resolve the platform category for a bolus event.
     *
     * @param bolus The bolus event to categorize.
     * @param provider Optional plugin category provider for pump-specific mapping.
     */
    fun resolve(bolus: BolusEvent, provider: BolusCategoryProvider?): BolusCategory {
        if (provider != null && bolus.category.isNotEmpty()) {
            val platformName = provider.toPlatformCategory(bolus.category)
            if (platformName != null) {
                return BolusCategory.fromName(platformName)
            }
        }
        return deriveFromFlags(bolus)
    }

    /**
     * Flag-based category derivation. Used as fallback when no plugin category
     * provider is available or the bolus has no category field (pre-migration data).
     */
    internal fun deriveFromFlags(bolus: BolusEvent): BolusCategory = when {
        bolus.isAutomated -> BolusCategory.AUTO_CORRECTION
        bolus.mealUnits > 0f && bolus.correctionUnits > 0f -> BolusCategory.FOOD_AND_CORRECTION
        bolus.isCorrection -> BolusCategory.CORRECTION
        bolus.mealUnits > 0f -> BolusCategory.FOOD
        // No flags set, no breakdown -- default to FOOD (manual bolus)
        else -> BolusCategory.FOOD
    }
}
