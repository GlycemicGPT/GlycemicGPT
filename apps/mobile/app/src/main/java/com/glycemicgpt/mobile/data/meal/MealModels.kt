package com.glycemicgpt.mobile.data.meal

import com.glycemicgpt.mobile.data.remote.dto.CommonFoodResponse
import com.glycemicgpt.mobile.data.remote.dto.FoodRecordResponse
import java.time.Instant

/**
 * Domain models for Meal Intelligence (Epic 50).
 *
 * Safety posture (NON-NEGOTIABLE): a carb estimate is a descriptive observation of a
 * photographed food, never a dose. Carbs are always a [CarbRange] plus a [CarbConfidence]
 * signal; nothing here represents insulin, units, or a bolus.
 */

/** A low/high carbohydrate range in grams. Never collapsed to a single number for display. */
data class CarbRange(val lowGrams: Double, val highGrams: Double)

/**
 * Client-side carb bounds, mirroring the backend's reject-not-clamp limits so a correction is
 * validated before it leaves the device. These describe food, never a dose.
 */
object CarbBounds {
    const val MIN_GRAMS = 0.0
    const val MAX_GRAMS = 1000.0

    /** Returns a human-readable reason a low/high range is invalid, or null if it is acceptable. */
    fun validate(lowGrams: Double, highGrams: Double): String? = when {
        lowGrams.isNaN() || highGrams.isNaN() -> "Enter a number of carbs in grams."
        lowGrams < MIN_GRAMS || highGrams < MIN_GRAMS -> "Carbs can't be negative."
        lowGrams > MAX_GRAMS || highGrams > MAX_GRAMS ->
            "Carbs can't exceed ${MAX_GRAMS.toInt()} g."
        lowGrams > highGrams -> "The low value must not exceed the high value."
        else -> null
    }

    /**
     * Parse two free-text gram inputs into a validated range. Shared by the food-record correction
     * and common-food edit flows so the parsing rules and copy never drift between them.
     */
    fun parse(lowText: String, highText: String): CarbInputResult {
        val low = lowText.trim().toDoubleOrNull()
        val high = highText.trim().toDoubleOrNull()
        if (low == null || high == null) {
            return CarbInputResult.Invalid("Enter both carb values in grams.")
        }
        validate(low, high)?.let { return CarbInputResult.Invalid(it) }
        return CarbInputResult.Valid(low, high)
    }
}

/** Outcome of parsing user-entered carb inputs via [CarbBounds.parse]. */
sealed interface CarbInputResult {
    data class Valid(val lowGrams: Double, val highGrams: Double) : CarbInputResult
    data class Invalid(val reason: String) : CarbInputResult
}

/** Model confidence in the estimate. Unknown when the provider returned nothing usable. */
enum class CarbConfidence {
    LOW,
    MEDIUM,
    HIGH,
    UNKNOWN,
    ;

    companion object {
        fun fromApi(value: String?): CarbConfidence = when (value?.trim()?.lowercase()) {
            "low" -> LOW
            "medium" -> MEDIUM
            "high" -> HIGH
            else -> UNKNOWN
        }
    }
}

/** Provenance of the carb value, mirroring the backend's `source` enum. */
enum class FoodRecordSource {
    AI_ESTIMATE,
    USER_CORRECTED,
    EXTERNAL_GROUNDED,
    UNKNOWN,
    ;

    companion object {
        fun fromApi(value: String?): FoodRecordSource = when (value?.trim()?.lowercase()) {
            "ai_estimate" -> AI_ESTIMATE
            "user_corrected" -> USER_CORRECTED
            "external_grounded" -> EXTERNAL_GROUNDED
            else -> UNKNOWN
        }
    }
}

/** A persisted meal photo + carb estimate, optionally corrected by the user. */
data class FoodRecord(
    val id: String,
    val mealTimestamp: Instant?,
    val foodDescription: String?,
    /** The original AI estimate. Always preserved, even after a correction. */
    val estimate: CarbRange,
    val confidence: CarbConfidence,
    val source: FoodRecordSource,
    /** The user's correction, if any. Null when the record has not been corrected. */
    val correction: CarbRange?,
    val correctedAt: Instant?,
    val commonFoodId: String?,
    val createdAt: Instant?,
) {
    /** Whether the user has corrected the AI estimate. */
    val isCorrected: Boolean get() = correction != null

    /** The carb range to show as the headline value: the correction if present, else the estimate. */
    val displayRange: CarbRange get() = correction ?: estimate
}

/** A saved per-user food baseline that future estimates can be grounded against. */
data class CommonFood(
    val id: String,
    val name: String,
    val carbs: CarbRange,
    val createdAt: Instant?,
    val updatedAt: Instant?,
)

/**
 * Parse an ISO-8601 timestamp defensively. Returns null on any unexpected format rather than
 * throwing, so a single malformed field never breaks a whole list.
 */
internal fun parseInstantOrNull(value: String?): Instant? {
    if (value.isNullOrBlank()) return null
    return try {
        Instant.parse(value)
    } catch (_: Exception) {
        try {
            java.time.OffsetDateTime.parse(value).toInstant()
        } catch (_: Exception) {
            null
        }
    }
}

fun FoodRecordResponse.toDomain(): FoodRecord {
    val correctionLow = correctedCarbsLow
    val correctionHigh = correctedCarbsHigh
    val correction = if (correctionLow != null && correctionHigh != null) {
        CarbRange(correctionLow, correctionHigh)
    } else {
        null
    }
    return FoodRecord(
        id = id,
        mealTimestamp = parseInstantOrNull(mealTimestamp),
        foodDescription = foodDescription,
        estimate = CarbRange(carbsLow, carbsHigh),
        confidence = CarbConfidence.fromApi(confidence),
        source = FoodRecordSource.fromApi(source),
        correction = correction,
        correctedAt = parseInstantOrNull(correctedAt),
        commonFoodId = commonFoodId,
        createdAt = parseInstantOrNull(createdAt),
    )
}

fun CommonFoodResponse.toDomain(): CommonFood = CommonFood(
    id = id,
    name = name,
    carbs = CarbRange(carbsLow, carbsHigh),
    createdAt = parseInstantOrNull(createdAt),
    updatedAt = parseInstantOrNull(updatedAt),
)
