package com.glycemicgpt.mobile.domain.model

/**
 * Per-category statistics for the insulin summary.
 */
data class CategoryStats(
    val count: Int,
    val totalUnits: Float,
    val foodPortion: Float,
    val correctionPortion: Float,
)

data class InsulinSummary(
    val totalDailyDose: Float,
    val basalUnits: Float,
    val bolusUnits: Float,
    val correctionUnits: Float,
    val basalPercent: Float,
    val bolusPercent: Float,
    val bolusCount: Int,
    val correctionCount: Int,
    // Portion-based delivery totals (U/day):
    val foodBolusUnits: Float = 0f,        // sum of meal portions across all boluses
    val correctionBolusUnits: Float = 0f,  // sum of correction portions across all boluses
    // Category breakdown: each bolus assigned to exactly one category
    val categoryBreakdown: Map<BolusCategory, CategoryStats> = emptyMap(),
    val periodDays: Float,
)
