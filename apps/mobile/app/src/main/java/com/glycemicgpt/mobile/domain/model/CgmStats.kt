package com.glycemicgpt.mobile.domain.model

data class CgmStats(
    val meanGlucose: Float,
    val stdDev: Float,
    val cvPercent: Float,
    val gmi: Float,
    val readingsCount: Int,
    /** Percentage of expected readings actually received [0..100]. */
    val cgmActivePercent: Float = 100f,
)
