package com.glycemicgpt.mobile.domain.model

import java.time.Instant

enum class BolusType {
    AUTO_CORRECTION,
    CORRECTION,
    MEAL,
    AUTO,
}

data class EnrichedBolusEvent(
    val units: Float,
    val bolusType: BolusType,
    val bgAtEvent: Int?,
    val iobAtEvent: Float?,
    val timestamp: Instant,
)
