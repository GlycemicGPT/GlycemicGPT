package com.glycemicgpt.mobile.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass
import java.time.Instant

/**
 * DTOs for the cloud-source mobile plugin (Story 43.8). These mirror the
 * backend's `NightscoutDataResponse` family (apps/api/src/schemas/nightscout.py).
 * The plugin pulls these and writes the rows into the same Room tables the BLE
 * plugins use, so the mobile dashboard populates without a second Nightscout
 * client on Android.
 */

@JsonClass(generateAdapter = true)
data class NightscoutConnectionDto(
    val id: String,
    val name: String,
    @Json(name = "is_active") val isActive: Boolean = true,
)

@JsonClass(generateAdapter = true)
data class NightscoutGlucoseReadingDto(
    @Json(name = "ns_id") val nsId: String? = null,
    @Json(name = "reading_timestamp") val readingTimestamp: Instant,
    val value: Int,
    val trend: String,
    @Json(name = "trend_rate") val trendRate: Float? = null,
    val source: String,
)

@JsonClass(generateAdapter = true)
data class NightscoutPumpEventDto(
    @Json(name = "ns_id") val nsId: String? = null,
    @Json(name = "event_timestamp") val eventTimestamp: Instant,
    @Json(name = "event_type") val eventType: String,
    val units: Float? = null,
    @Json(name = "duration_minutes") val durationMinutes: Int? = null,
    @Json(name = "is_automated") val isAutomated: Boolean = false,
    val source: String,
)

@JsonClass(generateAdapter = true)
data class NightscoutDataDto(
    @Json(name = "connection_id") val connectionId: String,
    @Json(name = "fetched_at") val fetchedAt: Instant,
    @Json(name = "effective_limit_per_array") val effectiveLimitPerArray: Int,
    @Json(name = "glucose_readings") val glucoseReadings: List<NightscoutGlucoseReadingDto>,
    @Json(name = "pump_events") val pumpEvents: List<NightscoutPumpEventDto>,
)
