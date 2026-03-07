package com.glycemicgpt.mobile.domain.model

/**
 * Platform-standard bolus categories. Pump-specific labels are mapped to these
 * by the plugin's [BolusCategoryProvider]. Used for insulin summary computation
 * and display.
 */
enum class BolusCategory(val displayName: String) {
    AUTO_CORRECTION("Auto Corr"),
    FOOD("Meal"),
    FOOD_AND_CORRECTION("Meal+Corr"),
    CORRECTION("Correction"),
    OVERRIDE("Override"),
    AI_SUGGESTED("AI Suggested"),
    OTHER("Other"),
    ;

    companion object {
        /** Resolve a category by its enum name, returning [OTHER] for unknown values. */
        fun fromName(name: String): BolusCategory =
            entries.firstOrNull { it.name == name } ?: OTHER
    }
}
