package com.glycemicgpt.mobile.data.local.entity

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "iob_readings",
    indices = [Index(value = ["timestampMs"])],
)
data class IoBReadingEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val iob: Float,
    val timestampMs: Long,
)

@Entity(
    tableName = "basal_readings",
    indices = [Index(value = ["timestampMs"], unique = true)],
)
data class BasalReadingEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val rate: Float,
    val isAutomated: Boolean,
    val activityMode: String,
    val timestampMs: Long,
)

@Entity(
    tableName = "bolus_events",
    indices = [
        Index(value = ["timestampMs"]),
        Index(value = ["units", "timestampMs"], unique = true),
    ],
)
data class BolusEventEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val units: Float,
    val isAutomated: Boolean,
    val isCorrection: Boolean,
    val timestampMs: Long,
)

@Entity(
    tableName = "battery_readings",
    indices = [Index(value = ["timestampMs"])],
)
data class BatteryReadingEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val percentage: Int,
    val isCharging: Boolean,
    val timestampMs: Long,
)

@Entity(
    tableName = "reservoir_readings",
    indices = [Index(value = ["timestampMs"])],
)
data class ReservoirReadingEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val unitsRemaining: Float,
    val timestampMs: Long,
)

@Entity(
    tableName = "cgm_readings",
    indices = [Index(value = ["timestampMs"], unique = true)],
)
data class CgmReadingEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val glucoseMgDl: Int,
    val trendArrow: String,
    val timestampMs: Long,
)
