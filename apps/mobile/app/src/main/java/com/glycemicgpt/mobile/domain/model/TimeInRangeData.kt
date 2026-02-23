package com.glycemicgpt.mobile.domain.model

data class TimeInRangeData(
    /** Percentage of readings below target range [0..100]. */
    val lowPercent: Float,
    /** Percentage of readings within target range [0..100]. */
    val inRangePercent: Float,
    /** Percentage of readings above target range [0..100]. */
    val highPercent: Float,
    /** Total number of CGM readings included in the time-in-range calculation. */
    val totalReadings: Int,
) {
    init {
        require(lowPercent in 0f..100f) { "lowPercent must be in 0..100" }
        require(inRangePercent in 0f..100f) { "inRangePercent must be in 0..100" }
        require(highPercent in 0f..100f) { "highPercent must be in 0..100" }
        require(totalReadings >= 0) { "totalReadings must be non-negative" }
        val sum = lowPercent + inRangePercent + highPercent
        require(sum < 0.5f || kotlin.math.abs(sum - 100f) <= 0.5f) {
            "percentages must sum to ~100 (got $sum)"
        }
    }
}
