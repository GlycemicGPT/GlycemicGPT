package com.glycemicgpt.mobile.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class DeviceRegistrationRequest(
    @Json(name = "device_token") val deviceToken: String,
    @Json(name = "device_name") val deviceName: String,
    val platform: String = "android",
    @Json(name = "device_fingerprint") val deviceFingerprint: String? = null,
    @Json(name = "app_version") val appVersion: String? = null,
    @Json(name = "build_type") val buildType: String? = null,
)

@JsonClass(generateAdapter = true)
data class DeviceRegistrationResponse(
    val id: String,
    @Json(name = "device_token") val deviceToken: String,
)

@JsonClass(generateAdapter = true)
data class AlertResponse(
    val id: String,
    @Json(name = "alert_type") val alertType: String,
    val severity: String,
    @Json(name = "current_value") val currentValue: Double,
    @Json(name = "predicted_value") val predictedValue: Double? = null,
    @Json(name = "iob_value") val iobValue: Double? = null,
    val message: String,
    @Json(name = "trend_rate") val trendRate: Double? = null,
    val timestamp: String,
    @Json(name = "patient_name") val patientName: String? = null,
    val acknowledged: Boolean = false,
)

@JsonClass(generateAdapter = true)
data class AcknowledgeResponse(
    val status: String,
    @Json(name = "alert_id") val alertId: String,
)
