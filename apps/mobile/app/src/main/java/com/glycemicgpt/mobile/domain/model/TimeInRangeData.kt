package com.glycemicgpt.mobile.domain.model

data class TimeInRangeData(
    /** Percentage of readings below urgent-low threshold [0..100]. */
    val urgentLowPercent: Float = 0f,
    /** Percentage of readings in [urgentLow, low) [0..100]. */
    val lowPercent: Float,
    /** Percentage of readings within target range [low, high] [0..100]. */
    val inRangePercent: Float,
    /** Percentage of readings in (high, urgentHigh] [0..100]. */
    val highPercent: Float,
    /** Percentage of readings above urgent-high threshold [0..100]. */
    val urgentHighPercent: Float = 0f,
    /** Total number of CGM readings included in the calculation. */
    val totalReadings: Int,
) {
    init {
        require(urgentLowPercent in 0f..100f) { "urgentLowPercent must be in 0..100" }
        require(lowPercent in 0f..100f) { "lowPercent must be in 0..100" }
        require(inRangePercent in 0f..100f) { "inRangePercent must be in 0..100" }
        require(highPercent in 0f..100f) { "highPercent must be in 0..100" }
        require(urgentHighPercent in 0f..100f) { "urgentHighPercent must be in 0..100" }
        require(totalReadings >= 0) { "totalReadings must be non-negative" }
        val sum = urgentLowPercent + lowPercent + inRangePercent + highPercent + urgentHighPercent
        require(sum < 0.5f || kotlin.math.abs(sum - 100f) <= 0.5f) {
            "percentages must sum to ~100 (got $sum)"
        }
    }
}
