package com.glycemicgpt.mobile.domain.model

import java.time.Instant

/**
 * A fingerstick blood glucose meter reading.
 * Glucose values are validated to be within clinically plausible range (20-500 mg/dL).
 */
data class BgmReading(
    val glucoseMgDl: Int,
    val timestamp: Instant,
    val meterName: String? = null,
) {
    init {
        require(glucoseMgDl in 20..500) {
            "glucoseMgDl must be in 20..500, was $glucoseMgDl"
        }
    }
}
