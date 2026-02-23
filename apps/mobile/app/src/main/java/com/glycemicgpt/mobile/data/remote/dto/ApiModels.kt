package com.glycemicgpt.mobile.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass
import java.time.Instant

@JsonClass(generateAdapter = true)
data class HealthResponse(
    val status: String,
)

@JsonClass(generateAdapter = true)
data class LoginRequest(
    val email: String,
    val password: String,
)

@JsonClass(generateAdapter = true)
data class LoginResponse(
    @Json(name = "access_token") val accessToken: String,
    @Json(name = "refresh_token") val refreshToken: String,
    @Json(name = "token_type") val tokenType: String,
    @Json(name = "expires_in") val expiresIn: Int,
    val user: UserDto,
)

@JsonClass(generateAdapter = true)
data class RefreshTokenRequest(
    @Json(name = "refresh_token") val refreshToken: String,
)

@JsonClass(generateAdapter = true)
data class UserDto(
    val id: String,
    val email: String,
    val role: String,
)

@JsonClass(generateAdapter = true)
data class PumpEventDto(
    @Json(name = "event_type") val eventType: String,
    @Json(name = "event_timestamp") val eventTimestamp: Instant,
    val units: Float? = null,
    @Json(name = "duration_minutes") val durationMinutes: Int? = null,
    @Json(name = "is_automated") val isAutomated: Boolean = false,
    @Json(name = "control_iq_mode") val controlIqMode: String? = null,
    @Json(name = "basal_adjustment_pct") val basalAdjustmentPct: Float? = null,
    @Json(name = "iob_at_event") val iobAtEvent: Float? = null,
    @Json(name = "bg_at_event") val bgAtEvent: Int? = null,
)

@JsonClass(generateAdapter = true)
data class PumpRawEventDto(
    @Json(name = "sequence_number") val sequenceNumber: Int,
    @Json(name = "raw_bytes_b64") val rawBytesB64: String,
    @Json(name = "event_type_id") val eventTypeId: Int,
    @Json(name = "pump_time_seconds") val pumpTimeSeconds: Long,
)

@JsonClass(generateAdapter = true)
data class PumpHardwareInfoDto(
    @Json(name = "serial_number") val serialNumber: Long,
    @Json(name = "model_number") val modelNumber: Long,
    @Json(name = "part_number") val partNumber: Long,
    @Json(name = "pump_rev") val pumpRev: String,
    @Json(name = "arm_sw_ver") val armSwVer: Long,
    @Json(name = "msp_sw_ver") val mspSwVer: Long,
    @Json(name = "config_a_bits") val configABits: Long,
    @Json(name = "config_b_bits") val configBBits: Long,
    @Json(name = "pcba_sn") val pcbaSn: Long,
    @Json(name = "pcba_rev") val pcbaRev: String,
    @Json(name = "pump_features") val pumpFeatures: Map<String, Boolean>,
)

@JsonClass(generateAdapter = true)
data class PumpPushRequest(
    val events: List<PumpEventDto>,
    @Json(name = "raw_events") val rawEvents: List<PumpRawEventDto>? = null,
    @Json(name = "pump_info") val pumpInfo: PumpHardwareInfoDto? = null,
    val source: String = "mobile",
)

@JsonClass(generateAdapter = true)
data class PumpPushResponse(
    val accepted: Int,
    val duplicates: Int,
    @Json(name = "raw_accepted") val rawAccepted: Int = 0,
    @Json(name = "raw_duplicates") val rawDuplicates: Int = 0,
)

@JsonClass(generateAdapter = true)
data class ChatRequest(
    val message: String,
)

@JsonClass(generateAdapter = true)
data class ChatResponse(
    val response: String,
    val disclaimer: String,
)

@JsonClass(generateAdapter = true)
data class AiProviderStatusResponse(
    @Json(name = "provider_type") val providerType: String,
    val status: String,
)

@JsonClass(generateAdapter = true)
data class GlucoseRangeResponse(
    @Json(name = "urgent_low") val urgentLow: Float,
    @Json(name = "low_target") val lowTarget: Float,
    @Json(name = "high_target") val highTarget: Float,
    @Json(name = "urgent_high") val urgentHigh: Float,
)

@JsonClass(generateAdapter = true)
data class SafetyLimitsResponse(
    @Json(name = "min_glucose_mgdl") val minGlucoseMgDl: Int,
    @Json(name = "max_glucose_mgdl") val maxGlucoseMgDl: Int,
    @Json(name = "max_basal_rate_milliunits") val maxBasalRateMilliunits: Int,
    @Json(name = "max_bolus_dose_milliunits") val maxBolusDoseMilliunits: Int,
    @Json(name = "updated_at") val updatedAt: String,
)
