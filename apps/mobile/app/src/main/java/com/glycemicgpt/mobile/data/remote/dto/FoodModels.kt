package com.glycemicgpt.mobile.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

/**
 * DTOs for the Meal Intelligence (Epic 50) food-records and common-foods APIs.
 *
 * Timestamps are kept as raw ISO-8601 strings (matching [AlertResponse]) and parsed
 * defensively in the mapper, so an unexpected offset format never crashes deserialization.
 *
 * Carbs are always a low/high range plus a confidence signal -- never a lone integer.
 * No field in this contract carries insulin, dose, or bolus information by design.
 * Fields the v1 UI does not consume (nutrition JSON, model/provider provenance) are omitted;
 * Moshi tolerates the extra response keys.
 */
@JsonClass(generateAdapter = true)
data class FoodRecordResponse(
    val id: String,
    @Json(name = "meal_timestamp") val mealTimestamp: String,
    @Json(name = "food_description") val foodDescription: String? = null,
    @Json(name = "carbs_low") val carbsLow: Double,
    @Json(name = "carbs_high") val carbsHigh: Double,
    // The empirical, dispersion-derived band (Story 50.H1) -- not the model's
    // self-reported confidence, which is no longer surfaced.
    val confidence: String? = null,
    val source: String,
    @Json(name = "corrected_carbs_low") val correctedCarbsLow: Double? = null,
    @Json(name = "corrected_carbs_high") val correctedCarbsHigh: Double? = null,
    @Json(name = "corrected_at") val correctedAt: String? = null,
    @Json(name = "common_food_id") val commonFoodId: String? = null,
    // Food-identity confirmation (Story 50.H2). food_description is the
    // AI-identified name; confirmed_food_name is the user's confirmed/corrected
    // identity (null until confirmed); external grounding only runs once
    // identity_confirmed is true. suggested_identity is a transient own-history
    // pre-fill ("looks like your saved X"), present on a fresh estimate only.
    @Json(name = "confirmed_food_name") val confirmedFoodName: String? = null,
    @Json(name = "identity_confirmed") val identityConfirmed: Boolean = false,
    @Json(name = "suggested_identity") val suggestedIdentity: String? = null,
    // Multi-sample dispersion detail (Story 50.H1). Present only on a fresh
    // estimate (create response); absent on later reads.
    @Json(name = "estimate_dispersion") val estimateDispersion: EstimateDispersionResponse? = null,
    // Glucose-framed nutrition (Story 50.N1): the assumed portion, the macros
    // with their "how this affects glucose" notes, and caveated net carbs. All
    // copy is server-cleared and rendered verbatim. Descriptive only -- never a dose.
    @Json(name = "nutrition_facts") val nutritionFacts: NutritionFactsResponse? = null,
    // Grounding-backed comorbidity nutrition: saturated fat / sugars /
    // sodium when an authoritative source published them. GROUNDING-ONLY and
    // identity-gated; absent on a record with no grounded comorbidity data.
    @Json(name = "comorbidity_nutrition")
    val comorbidityNutrition: ComorbidityNutritionResponse? = null,
    @Json(name = "created_at") val createdAt: String,
)

/**
 * Grounding-backed comorbidity / label nutrition. GROUNDING-ONLY and
 * identity-gated: published reference figures for blood-pressure / cardiovascular
 * awareness, attributed to their [source] (distinct from the vision estimate), with
 * a [disclaimer] carrying the never-dose framing. [sugarNote] (the "sugar-free isn't
 * carb-free" reminder) is present only when a sugars figure is surfaced. Descriptive
 * only -- never a dose. Only consumed fields are declared.
 */
@JsonClass(generateAdapter = true)
data class ComorbidityNutritionResponse(
    val facts: List<ComorbidityFactResponse> = emptyList(),
    @Json(name = "sugar_note") val sugarNote: String? = null,
    val source: String? = null,
    @Json(name = "trust_tier") val trustTier: String? = null,
    val disclaimer: String? = null,
)

@JsonClass(generateAdapter = true)
data class ComorbidityFactResponse(
    val key: String,
    val label: String,
    val value: Double,
    val unit: String,
    val note: String? = null,
)

/**
 * Display-ready, glucose-framed nutrition (Story 50.N1). Server-computed, never
 * persisted: the assumed [portion] (the estimate's primary sanity-check), the
 * framed [macros], and caveated [netCarbs]. [disclaimer] carries the never-dose
 * framing over the whole block. Only consumed fields are declared.
 */
@JsonClass(generateAdapter = true)
data class NutritionFactsResponse(
    val portion: String? = null,
    val macros: List<MacroFactResponse> = emptyList(),
    @Json(name = "net_carbs") val netCarbs: NetCarbsResponse? = null,
    val disclaimer: String? = null,
)

@JsonClass(generateAdapter = true)
data class MacroFactResponse(
    val key: String,
    val label: String,
    val value: Double,
    val unit: String,
    @Json(name = "glucose_note") val glucoseNote: String? = null,
)

@JsonClass(generateAdapter = true)
data class NetCarbsResponse(
    val low: Double,
    val high: Double,
    val caveat: String,
)

/**
 * How much the N vision samples of one photo disagreed (Story 50.H1). The UI uses
 * this to communicate uncertainty viscerally; only the consumed fields are
 * declared (Moshi tolerates the rest).
 */
@JsonClass(generateAdapter = true)
data class EstimateDispersionResponse(
    val note: String? = null,
    @Json(name = "wide_spread") val wideSpread: Boolean = false,
    @Json(name = "identity_agreement") val identityAgreement: Boolean = true,
)

@JsonClass(generateAdapter = true)
data class FoodRecordListResponse(
    val records: List<FoodRecordResponse>,
    val total: Int,
)

@JsonClass(generateAdapter = true)
data class FoodRecordCorrectionRequest(
    @Json(name = "corrected_carbs_low") val correctedCarbsLow: Double,
    @Json(name = "corrected_carbs_high") val correctedCarbsHigh: Double,
)

@JsonClass(generateAdapter = true)
data class FoodRecordIdentityRequest(
    @Json(name = "confirmed_food_name") val confirmedFoodName: String,
)

/**
 * The "how was this estimated" provenance trail (Story 50.H3). Descriptive only.
 * The model's self-reported confidence is intentionally NOT part of this contract
 * (the server strips it). Only consumed fields are declared.
 */
@JsonClass(generateAdapter = true)
data class FoodRecordAuditResponse(
    @Json(name = "food_record_id") val foodRecordId: String,
    val samples: List<AuditSampleResponse> = emptyList(),
    val dispersion: AuditDispersionResponse? = null,
    val precedence: AuditPrecedenceResponse? = null,
    @Json(name = "created_at") val createdAt: String? = null,
)

@JsonClass(generateAdapter = true)
data class AuditSampleResponse(
    @Json(name = "carbs_low") val carbsLow: Double? = null,
    @Json(name = "carbs_high") val carbsHigh: Double? = null,
    val identity: String? = null,
)

@JsonClass(generateAdapter = true)
data class AuditDispersionResponse(
    val confidence: String? = null,
    @Json(name = "samples_used") val samplesUsed: Int? = null,
    @Json(name = "wide_spread") val wideSpread: Boolean? = null,
    @Json(name = "identity_agreement") val identityAgreement: Boolean? = null,
)

@JsonClass(generateAdapter = true)
data class AuditPrecedenceResponse(
    val outcome: String? = null,
    @Json(name = "chosen_source") val chosenSource: String? = null,
    @Json(name = "identity_used") val identityUsed: String? = null,
    @Json(name = "identity_confirmed") val identityConfirmed: Boolean? = null,
)

@JsonClass(generateAdapter = true)
data class SaveAsCommonFoodRequest(
    val name: String,
)

@JsonClass(generateAdapter = true)
data class CommonFoodResponse(
    val id: String,
    val name: String,
    @Json(name = "carbs_low") val carbsLow: Double,
    @Json(name = "carbs_high") val carbsHigh: Double,
    @Json(name = "created_at") val createdAt: String,
    @Json(name = "updated_at") val updatedAt: String,
)

@JsonClass(generateAdapter = true)
data class CommonFoodListResponse(
    @Json(name = "common_foods") val commonFoods: List<CommonFoodResponse>,
    val total: Int,
)

@JsonClass(generateAdapter = true)
data class CommonFoodUpdateRequest(
    val name: String? = null,
    @Json(name = "carbs_low") val carbsLow: Double? = null,
    @Json(name = "carbs_high") val carbsHigh: Double? = null,
)
