package com.glycemicgpt.mobile.domain.model

import java.time.Instant

enum class BolusType {
    AUTO_CORRECTION,
    CORRECTION,
    MEAL,
    MEAL_WITH_CORRECTION,
    AUTO,
}

data class EnrichedBolusEvent(
    val units: Float,
    val bolusType: BolusType,
    val reason: String,
    val correctionUnits: Float,
    val mealUnits: Float,
    val bgAtEvent: Int?,
    val iobAtEvent: Float?,
    val timestamp: Instant,
) {
    init {
        require(units in 0f..BolusEvent.MAX_BOLUS_UNITS) { "units must be 0-${BolusEvent.MAX_BOLUS_UNITS} U" }
        require(correctionUnits in 0f..BolusEvent.MAX_BOLUS_UNITS) { "correctionUnits must be 0-${BolusEvent.MAX_BOLUS_UNITS} U" }
        require(mealUnits in 0f..BolusEvent.MAX_BOLUS_UNITS) { "mealUnits must be 0-${BolusEvent.MAX_BOLUS_UNITS} U" }
        bgAtEvent?.let { require(it in 20..500) { "bgAtEvent must be 20-500 mg/dL" } }
    }
}
