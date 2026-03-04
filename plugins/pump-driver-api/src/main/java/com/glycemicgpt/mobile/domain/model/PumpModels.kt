package com.glycemicgpt.mobile.domain.model

import java.time.Instant

data class IoBReading(
    val iob: Float,
    val timestamp: Instant,
)

data class BasalReading(
    val rate: Float,
    val isAutomated: Boolean,
    val activityMode: PumpActivityMode,
    val timestamp: Instant,
)

/**
 * Pump activity modes -- pump-level feature, independent of Control-IQ automation.
 *
 * Sleep and Exercise are pump activity modes that adjust target ranges and basal
 * profiles. They exist on all Tandem pumps regardless of whether Control-IQ is
 * enabled. NONE means no special activity mode is active (normal operation).
 */
enum class PumpActivityMode {
    NONE,
    SLEEP,
    EXERCISE,
}

/** Backwards-compat alias. Remove once all consumers migrate. */
@Deprecated("Use PumpActivityMode", ReplaceWith("PumpActivityMode"))
typealias ControlIqMode = PumpActivityMode

/**
 * A bolus delivery event from a pump.
 *
 * [units] is the actual delivered total (from pump hardware). [correctionUnits] and [mealUnits]
 * are the *requested* breakdown (correction vs meal portions). These may not sum to [units]
 * because: (1) partial delivery (occlusion, user cancel) means delivered < requested,
 * (2) the status response (opcode 0x30) has no breakdown so both are 0, and
 * (3) automated boluses set mealUnits=0 regardless of correction portion.
 */
data class BolusEvent(
    val units: Float,
    val isAutomated: Boolean,
    val isCorrection: Boolean,
    val correctionUnits: Float = 0f,
    val mealUnits: Float = 0f,
    val source: String = "",
    val timestamp: Instant,
) {
    init {
        require(units >= 0f) { "BolusEvent units must be non-negative, was $units" }
        require(units <= MAX_BOLUS_UNITS) {
            "BolusEvent units ($units) exceeds hard safety cap of $MAX_BOLUS_UNITS U"
        }
        require(correctionUnits >= 0f) { "correctionUnits must be non-negative" }
        require(correctionUnits <= MAX_BOLUS_UNITS) {
            "correctionUnits ($correctionUnits) exceeds hard safety cap of $MAX_BOLUS_UNITS U"
        }
        require(mealUnits >= 0f) { "mealUnits must be non-negative" }
        require(mealUnits <= MAX_BOLUS_UNITS) {
            "mealUnits ($mealUnits) exceeds hard safety cap of $MAX_BOLUS_UNITS U"
        }
    }

    companion object {
        /** Hard safety cap: no single bolus can exceed 25 units (Tandem hardware max is 25U). */
        const val MAX_BOLUS_UNITS: Float = 25f
    }
}

data class PumpSettings(
    val firmwareVersion: String,
    val serialNumber: String,
    val modelNumber: String,
)

data class BatteryStatus(
    val percentage: Int,
    val isCharging: Boolean,
    val timestamp: Instant,
)

data class ReservoirReading(
    val unitsRemaining: Float,
    val timestamp: Instant,
)

data class CgmReading(
    val glucoseMgDl: Int,
    val trendArrow: CgmTrend,
    val timestamp: Instant,
) {
    init {
        require(glucoseMgDl in 20..500) {
            "glucoseMgDl must be in 20..500, was $glucoseMgDl"
        }
    }
}

enum class CgmTrend {
    DOUBLE_UP,
    SINGLE_UP,
    FORTY_FIVE_UP,
    FLAT,
    FORTY_FIVE_DOWN,
    SINGLE_DOWN,
    DOUBLE_DOWN,
    UNKNOWN,
}

/**
 * Sequence range from HistoryLogStatusResponse (opcode 59).
 *
 * Sequence numbers are unsigned 32-bit on the wire but stored as signed Int
 * (Kotlin has no unsigned int). Current pump values (~1.3M) are well within
 * the signed Int max (2,147,483,647), so this is safe for the foreseeable future.
 */
data class HistoryLogRange(
    val firstSeq: Int,
    val lastSeq: Int,
)

data class HistoryLogRecord(
    val sequenceNumber: Int,
    val rawBytesB64: String,
    val eventTypeId: Int,
    val pumpTimeSeconds: Long,
)

data class PumpHardwareInfo(
    val serialNumber: Long,
    val modelNumber: Long,
    val partNumber: Long,
    val pumpRev: String,
    val armSwVer: Long,
    val mspSwVer: Long,
    val configABits: Long,
    val configBBits: Long,
    val pcbaSn: Long,
    val pcbaRev: String,
    val pumpFeatures: Map<String, Boolean>,
)

enum class ConnectionState {
    DISCONNECTED,
    SCANNING,
    CONNECTING,
    AUTHENTICATING,
    AUTH_FAILED,
    CONNECTED,
    RECONNECTING,
}
