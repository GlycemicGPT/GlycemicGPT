package com.glycemicgpt.mobile.domain.model

data class AgpBucket(
    val hour: Int,
    val p10: Float,
    val p25: Float,
    val p50: Float,
    val p75: Float,
    val p90: Float,
    val count: Int,
)

data class AgpProfile(
    val buckets: List<AgpBucket>,
    val totalReadings: Int,
    val periodDays: Int,
)
