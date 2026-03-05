package com.glycemicgpt.mobile.domain.model

data class InsulinSummary(
    val totalDailyDose: Float,
    val basalUnits: Float,
    val bolusUnits: Float,
    val correctionUnits: Float,
    val basalPercent: Float,
    val bolusPercent: Float,
    val bolusCount: Int,
    val correctionCount: Int,
    // Per-category bolus breakdown (U/day), mirrors pump Delivery Summary:
    val foodBolusUnits: Float = 0f,        // pump "Food Bolus" + "Food Only" (BolusType.MEAL)
    val correctionBolusUnits: Float = 0f,  // pump "Correction Bolus" (BolusType.AUTO_CORRECTION + AUTO)
    val bgFoodUnits: Float = 0f,           // pump "BG + Food" (BolusType.MEAL_WITH_CORRECTION)
    val bgOnlyUnits: Float = 0f,           // pump "BG Only" (BolusType.CORRECTION)
    val periodDays: Float,
)
