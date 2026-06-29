package com.glycemicgpt.mobile.data.repository

import com.glycemicgpt.mobile.data.meal.CommonFood
import com.glycemicgpt.mobile.data.meal.FoodRecord
import com.glycemicgpt.mobile.data.meal.MealAudit
import com.glycemicgpt.mobile.data.meal.MealException
import com.glycemicgpt.mobile.data.meal.toDomain
import com.glycemicgpt.mobile.data.remote.GlycemicGptApi
import com.glycemicgpt.mobile.data.remote.dto.CommonFoodUpdateRequest
import com.glycemicgpt.mobile.data.remote.dto.FoodRecordCorrectionRequest
import com.glycemicgpt.mobile.data.remote.dto.FoodRecordIdentityRequest
import com.glycemicgpt.mobile.data.remote.dto.SaveAsCommonFoodRequest
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import kotlinx.coroutines.CancellationException
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.MediaType.Companion.toMediaType
import retrofit2.Response
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Named
import javax.inject.Singleton

/**
 * Data access for Meal Intelligence (Epic 50). Wraps the food-records / common-foods APIs and
 * translates HTTP failures into typed [MealException]s so the UI can degrade gracefully
 * (feature-off, vision-unavailable) rather than showing a raw error.
 *
 * The photo upload routes through the long-timeout [chatApi] because it triggers a vision-model
 * inference that can take far longer than the standard 15s budget.
 */
@Singleton
class MealRepository @Inject constructor(
    private val api: GlycemicGptApi,
    @Named("chat") private val chatApi: GlycemicGptApi,
    moshi: Moshi,
) {
    // The FastAPI error envelope is parsed as a raw object map rather than a codegen DTO: its
    // `detail` is a plain string for our HTTPExceptions but a list of objects for Pydantic
    // request-validation failures, so a fixed-shape adapter can't model it.
    private val errorBodyAdapter = moshi.adapter<Map<String, Any?>>(
        Types.newParameterizedType(Map::class.java, String::class.java, Any::class.java),
    )

    /** Upload a compressed JPEG and return the persisted estimate. */
    suspend fun uploadPhoto(jpegBytes: ByteArray): Result<FoodRecord> {
        val body = jpegBytes.toRequestBody(JPEG_MEDIA_TYPE)
        val part = MultipartBody.Part.createFormData("file", "meal.jpg", body)
        return body { chatApi.uploadFoodPhoto(part) }.map { it.toDomain() }
    }

    suspend fun listFoodRecords(limit: Int = DEFAULT_PAGE, offset: Int = 0): Result<List<FoodRecord>> =
        body { api.listFoodRecords(limit = limit, offset = offset) }
            .map { resp -> resp.records.map { it.toDomain() } }

    /**
     * Cheapest call that still exercises the flag-gated surface, used only to detect feature-off
     * (404) vs reachable. Success/data is irrelevant -- callers inspect the failure type.
     */
    suspend fun probeAvailability(): Result<Unit> =
        listFoodRecords(limit = 1).map { }

    suspend fun deleteFoodRecord(recordId: String): Result<Unit> =
        noContent { api.deleteFoodRecord(recordId) }

    suspend fun correctRecord(
        recordId: String,
        correctedCarbsLow: Double,
        correctedCarbsHigh: Double,
    ): Result<FoodRecord> = body {
        api.correctFoodRecord(
            recordId,
            FoodRecordCorrectionRequest(
                correctedCarbsLow = correctedCarbsLow,
                correctedCarbsHigh = correctedCarbsHigh,
            ),
        )
    }.map { it.toDomain() }

    /** Confirm/correct *what the food is* (Story 50.H2); opens the grounding gate. */
    suspend fun confirmIdentity(recordId: String, confirmedFoodName: String): Result<FoodRecord> =
        body {
            api.confirmFoodIdentity(
                recordId,
                FoodRecordIdentityRequest(confirmedFoodName = confirmedFoodName.trim()),
            )
        }.map { it.toDomain() }

    /** Fetch the "how was this estimated" provenance trail (Story 50.H3). */
    suspend fun getAudit(recordId: String): Result<MealAudit> =
        body { api.getFoodRecordAudit(recordId) }.map { it.toDomain() }

    suspend fun saveAsCommonFood(recordId: String, name: String): Result<CommonFood> =
        body { api.saveRecordAsCommonFood(recordId, SaveAsCommonFoodRequest(name = name)) }
            .map { it.toDomain() }

    suspend fun listCommonFoods(limit: Int = DEFAULT_PAGE, offset: Int = 0): Result<List<CommonFood>> =
        body { api.listCommonFoods(limit = limit, offset = offset) }
            .map { resp -> resp.commonFoods.map { it.toDomain() } }

    suspend fun updateCommonFood(
        commonFoodId: String,
        name: String? = null,
        carbsLow: Double? = null,
        carbsHigh: Double? = null,
    ): Result<CommonFood> = body {
        api.updateCommonFood(
            commonFoodId,
            CommonFoodUpdateRequest(name = name, carbsLow = carbsLow, carbsHigh = carbsHigh),
        )
    }.map { it.toDomain() }

    suspend fun deleteCommonFood(commonFoodId: String): Result<Unit> =
        noContent { api.deleteCommonFood(commonFoodId) }

    /** Run a call expected to return a body, mapping HTTP/IO failures to typed [MealException]s. */
    private suspend fun <T> body(block: suspend () -> Response<T>): Result<T> = guard {
        val response = block()
        if (response.isSuccessful) {
            response.body()?.let { Result.success(it) }
                ?: Result.failure(MealException.EstimateFailed("The server returned an empty response."))
        } else {
            Result.failure(mapErrorResponse(response))
        }
    }

    /** Run a call whose success is a 204/empty body. */
    private suspend fun noContent(block: suspend () -> Response<Unit>): Result<Unit> = guard {
        val response = block()
        if (response.isSuccessful) {
            Result.success(Unit)
        } else {
            Result.failure(mapErrorResponse(response))
        }
    }

    private inline fun <T> guard(block: () -> Result<T>): Result<T> = try {
        block()
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        Result.failure(e)
    }

    /**
     * Map any non-2xx meal-endpoint response to a typed [MealException], reading the error body
     * exactly once.
     *
     * Server errors (5xx) on any meal call also emit an R8-safe diagnostic so an opaque failure can
     * be diagnosed on its next occurrence (the photo upload is the motivating case): release builds
     * ship no Sentry DSN, so this logcat trail is the only client-side signal we get. The
     * content-type + body prefix distinguish an app-backend error (JSON `{"detail":...}`) from an
     * edge/proxy one (HTML/empty), and the host confirms the request actually reached the real
     * backend.
     */
    private fun mapErrorResponse(response: Response<*>): MealException {
        val errorBody = response.errorBody()
        val contentType = errorBody?.contentType()?.toString()
        // ResponseBody.string() consumes the stream and may only be called once.
        val raw = try {
            errorBody?.string()?.takeIf { it.isNotBlank() }
        } catch (_: Exception) {
            null
        }
        if (response.code() >= 500) {
            // Timber.e survives R8 (only d/v are stripped) and the release ReleaseTree scrubs
            // tokens/emails/glucose before anything reaches logcat.
            val request = response.raw().request
            Timber.e(
                "Meal API server error %d on %s %s%s (content-type=%s): %s",
                response.code(),
                request.method,
                request.url.host,
                request.url.encodedPath,
                contentType ?: "none",
                raw?.take(MAX_LOGGED_ERROR_BODY) ?: "<empty body>",
            )
        }
        return mapError(response.code(), parseDetail(raw))
    }

    /** Extract the human message from a FastAPI error body, tolerating both the string and the
     *  Pydantic list-of-objects shapes of `detail`. */
    private fun parseDetail(raw: String?): String? = try {
        val parsed = raw?.let { errorBodyAdapter.fromJson(it) }
        when (val detail = parsed?.get("detail")) {
            is String -> detail
            is List<*> -> (detail.firstOrNull() as? Map<*, *>)?.get("msg") as? String
            else -> null
        }
    } catch (_: Exception) {
        null
    }

    private fun mapError(code: Int, detail: String?): MealException {
        val message = detail?.trim().orEmpty()
        return when (code) {
            // A decode failure on an already-re-encoded upload means the source was unusable;
            // "try a different photo" is more honest than the generic "try again".
            400 -> MealException.EstimateFailed(
                message.ifEmpty { "That photo couldn't be processed. Try a different one." },
            )
            404 -> when {
                message.contains(DETAIL_FEATURE_OFF, ignoreCase = true) -> MealException.FeatureDisabled()
                message.contains(DETAIL_NO_PROVIDER, ignoreCase = true) -> MealException.NoAiProvider()
                else -> MealException.NotFound(message.ifEmpty { "That item could not be found." })
            }
            409 -> MealException.NameConflict(message.ifEmpty { "A common food with that name already exists." })
            413 -> MealException.ImageTooLarge()
            415 -> MealException.UnsupportedImage()
            422 -> when {
                message.contains(DETAIL_VISION, ignoreCase = true) -> MealException.VisionUnavailable()
                message.isNotEmpty() -> MealException.Validation(message)
                else -> MealException.EstimateFailed("That request couldn't be processed. Please try again.")
            }
            429 -> MealException.RateLimited()
            502 -> MealException.EstimateFailed(
                "The AI vision service is temporarily unavailable. Please try again in a moment.",
            )
            // Distinct, honest copy for the server-error family (mirrors the 502 convention of
            // owning user-facing copy rather than echoing the backend's technical detail). The raw
            // detail still lands in the 5xx diagnostic above for triage.
            500 -> MealException.EstimateFailed(
                "Something went wrong on our end while analyzing your photo. Please try again.",
            )
            503 -> MealException.EstimateFailed(
                "The service is temporarily unavailable. Please try again in a moment.",
            )
            504 -> MealException.EstimateFailed(
                "The request took too long to process. Please try again.",
            )
            else -> MealException.EstimateFailed(
                message.ifEmpty { "Something went wrong (HTTP $code). Please try again." },
            )
        }
    }

    private companion object {
        const val DEFAULT_PAGE = 50

        // Cap how much of an error body we log: enough to tell a FastAPI `{"detail":...}` JSON
        // payload from an edge-proxy HTML/empty body, without dumping a large response.
        const val MAX_LOGGED_ERROR_BODY = 200
        val JPEG_MEDIA_TYPE = "image/jpeg".toMediaType()

        // Substrings of the backend's `detail` copy (apps/api/src/routers/_meal_intelligence.py
        // and food_records.py). The MealRepositoryTest cases pin these exact strings.
        const val DETAIL_FEATURE_OFF = "not enabled"
        // Specific enough to match "No AI provider configured." / "...for your AI provider."
        // without catching an unrelated 404 whose copy merely mentions a "provider".
        const val DETAIL_NO_PROVIDER = "ai provider"
        const val DETAIL_VISION = "vision"
    }
}
