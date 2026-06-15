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
    val confidence: String? = null,
    val source: String,
    @Json(name = "corrected_carbs_low") val correctedCarbsLow: Double? = null,
    @Json(name = "corrected_carbs_high") val correctedCarbsHigh: Double? = null,
    @Json(name = "corrected_at") val correctedAt: String? = null,
    @Json(name = "common_food_id") val commonFoodId: String? = null,
    @Json(name = "created_at") val createdAt: String,
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
