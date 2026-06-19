package com.glycemicgpt.mobile.data.meal

import com.glycemicgpt.mobile.data.remote.dto.CommonFoodResponse
import com.glycemicgpt.mobile.data.remote.dto.FoodRecordAuditResponse
import com.glycemicgpt.mobile.data.remote.dto.FoodRecordResponse
import com.glycemicgpt.mobile.data.remote.dto.NutritionFactsResponse
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

/**
 * How much the AI's repeated reads of one photo disagreed (Story 50.H1).
 *
 * The [confidence] on a [FoodRecord] is already the empirical band derived from
 * this spread; this carries the visceral, human-readable detail. Present only on
 * a fresh estimate (the create response); null on records loaded from history.
 */
data class MealDispersion(
    /** Plain-language uncertainty note (already dosing-scrubbed server-side). */
    val note: String?,
    /** The reads disagreed enough to warrant a visible "rough guess" treatment. */
    val wideSpread: Boolean,
    /** Whether the reads agreed on *what the food is* (false => confirm identity). */
    val identityAgreement: Boolean,
)

/**
 * Glucose-framed nutrition for a meal (Story 50.N1). Descriptive only: the
 * [portion] is the estimate's primary sanity-check, the [macros] carry "how this
 * affects glucose" notes, and [netCarbs] travels behind a never-dose caveat.
 * Nothing here is a dose. All copy is server-cleared and rendered verbatim.
 */
data class MealNutritionFacts(
    val portion: String?,
    val macros: List<MealMacro>,
    val netCarbs: MealNetCarbs?,
    val disclaimer: String?,
)

/** One glucose-relevant macro with its descriptive, no-timing-number framing. */
data class MealMacro(
    val key: String,
    val label: String,
    val value: Double,
    val unit: String,
    val glucoseNote: String?,
)

/**
 * Net carbs (total carbs minus fiber), surfaced only behind [caveat] -- clearly
 * secondary to the total carb range and never a dosing input.
 */
data class MealNetCarbs(
    val low: Double,
    val high: Double,
    val caveat: String,
)

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
    /** Multi-sample dispersion detail (Story 50.H1). Null on history reads. */
    val dispersion: MealDispersion? = null,
    /**
     * Food-identity confirmation (Story 50.H2). [foodDescription] is the AI's
     * guess; [confirmedFoodName] is the user's confirmed/corrected identity (null
     * until confirmed). External grounding only runs once [identityConfirmed].
     */
    val confirmedFoodName: String? = null,
    val identityConfirmed: Boolean = false,
    /** Own-history pre-fill ("looks like your saved X"); fresh estimate only. */
    val suggestedIdentity: String? = null,
    /** Glucose-framed nutrition (Story 50.N1): portion + macros + net carbs. */
    val nutritionFacts: MealNutritionFacts? = null,
) {
    /** Whether the user has corrected the AI estimate. */
    val isCorrected: Boolean get() = correction != null

    /** The carb range to show as the headline value: the correction if present, else the estimate. */
    val displayRange: CarbRange get() = correction ?: estimate

    /** The identity to show: the user's confirmed name if present, else the AI's guess. */
    val displayIdentity: String? get() = confirmedFoodName?.takeIf { it.isNotBlank() } ?: foodDescription
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
        dispersion = estimateDispersion?.let {
            MealDispersion(
                note = it.note?.takeIf { note -> note.isNotBlank() },
                wideSpread = it.wideSpread,
                identityAgreement = it.identityAgreement,
            )
        },
        confirmedFoodName = confirmedFoodName,
        identityConfirmed = identityConfirmed,
        suggestedIdentity = suggestedIdentity?.takeIf { it.isNotBlank() },
        nutritionFacts = nutritionFacts?.toDomain(),
    )
}

private fun NutritionFactsResponse.toDomain(): MealNutritionFacts = MealNutritionFacts(
    portion = portion?.takeIf { it.isNotBlank() },
    // Drop any non-finite macro value defensively. The server already rejects
    // these, but the client mirrors that so a malformed response can never render
    // a NaN/Infinity figure on a medical surface.
    macros = macros.mapNotNull { macro ->
        macro.takeIf { it.value.isFinite() }?.let {
            MealMacro(
                key = it.key,
                label = it.label,
                value = it.value,
                unit = it.unit,
                glucoseNote = it.glucoseNote?.takeIf { note -> note.isNotBlank() },
            )
        }
    },
    // Skip net carbs that are non-finite or inverted (mirrors the server bounds).
    netCarbs = netCarbs
        ?.takeIf { it.low.isFinite() && it.high.isFinite() && it.low <= it.high }
        ?.let { MealNetCarbs(low = it.low, high = it.high, caveat = it.caveat) },
    disclaimer = disclaimer?.takeIf { it.isNotBlank() },
)

/**
 * The "how was this estimated" provenance trail (Story 50.H3). Descriptive only;
 * the model's self-reported confidence is intentionally not represented here.
 */
data class MealAudit(
    val foodRecordId: String,
    val samples: List<AuditSample>,
    val confidence: CarbConfidence,
    val samplesUsed: Int?,
    val wideSpread: Boolean?,
    val identityAgreement: Boolean?,
    val grounded: Boolean,
    val groundingSource: String?,
    val identityUsed: String?,
)

/** One raw vision sample as shown in the audit trail. */
data class AuditSample(
    val carbs: CarbRange?,
    val identity: String?,
)

fun FoodRecordAuditResponse.toDomain(): MealAudit = MealAudit(
    foodRecordId = foodRecordId,
    samples = samples.map {
        val low = it.carbsLow
        val high = it.carbsHigh
        AuditSample(
            carbs = if (low != null && high != null) CarbRange(low, high) else null,
            identity = it.identity,
        )
    },
    confidence = CarbConfidence.fromApi(dispersion?.confidence),
    samplesUsed = dispersion?.samplesUsed,
    wideSpread = dispersion?.wideSpread,
    identityAgreement = dispersion?.identityAgreement,
    grounded = precedence?.outcome == "grounded",
    groundingSource = precedence?.chosenSource,
    identityUsed = precedence?.identityUsed,
)

fun CommonFoodResponse.toDomain(): CommonFood = CommonFood(
    id = id,
    name = name,
    carbs = CarbRange(carbsLow, carbsHigh),
    createdAt = parseInstantOrNull(createdAt),
    updatedAt = parseInstantOrNull(updatedAt),
)
