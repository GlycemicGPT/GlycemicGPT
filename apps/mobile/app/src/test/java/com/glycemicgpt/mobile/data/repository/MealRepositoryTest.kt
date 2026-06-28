package com.glycemicgpt.mobile.data.repository

import com.glycemicgpt.mobile.data.meal.MealException
import com.glycemicgpt.mobile.data.remote.GlycemicGptApi
import com.glycemicgpt.mobile.data.remote.dto.CommonFoodResponse
import com.glycemicgpt.mobile.data.remote.dto.FoodRecordListResponse
import com.glycemicgpt.mobile.data.remote.dto.FoodRecordResponse
import com.squareup.moshi.Moshi
import io.mockk.coEvery
import io.mockk.mockk
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.Response
import timber.log.Timber

class MealRepositoryTest {

    private val api = mockk<GlycemicGptApi>()
    private val chatApi = mockk<GlycemicGptApi>()
    private val moshi = Moshi.Builder().build()
    private val repository = MealRepository(api, chatApi, moshi)

    @After
    fun tearDown() {
        // The diagnostic-logging test plants a Timber tree; never leak it into sibling tests.
        Timber.uprootAll()
    }

    /** Captures the formatted messages Timber emits, so a test can assert on the diagnostic. */
    private class RecordingTree : Timber.Tree() {
        val messages = mutableListOf<String>()
        override fun log(priority: Int, tag: String?, message: String, t: Throwable?) {
            messages.add(message)
        }
    }

    private fun errorBody(detail: String) =
        """{"detail":"$detail"}""".toResponseBody("application/json".toMediaType())

    private fun sampleRecord(source: String = "ai_estimate") = FoodRecordResponse(
        id = "rec-1",
        mealTimestamp = "2026-06-14T12:00:00Z",
        foodDescription = "pasta",
        carbsLow = 40.0,
        carbsHigh = 55.0,
        confidence = "high",
        source = source,
        createdAt = "2026-06-14T12:00:05Z",
    )

    @Test
    fun `uploadPhoto returns the mapped record on success`() = runTest {
        coEvery { chatApi.uploadFoodPhoto(any<MultipartBody.Part>()) } returns
            Response.success(sampleRecord())

        val result = repository.uploadPhoto(ByteArray(16))

        assertTrue(result.isSuccess)
        assertEquals(40.0, result.getOrThrow().estimate.lowGrams, 0.0)
    }

    @Test
    fun `uploadPhoto maps 422 vision detail to VisionUnavailable`() = runTest {
        coEvery { chatApi.uploadFoodPhoto(any<MultipartBody.Part>()) } returns
            Response.error(422, errorBody("Vision is not available on your current AI provider."))

        val result = repository.uploadPhoto(ByteArray(16))

        assertTrue(result.exceptionOrNull() is MealException.VisionUnavailable)
    }

    @Test
    fun `uploadPhoto maps 422 non-vision detail to Validation`() = runTest {
        coEvery { chatApi.uploadFoodPhoto(any<MultipartBody.Part>()) } returns
            Response.error(422, errorBody("The estimate was outside the supported range."))

        val e = repository.uploadPhoto(ByteArray(16)).exceptionOrNull()
        assertTrue(e is MealException.Validation)
        assertTrue(e!!.message!!.contains("supported range"))
    }

    @Test
    fun `uploadPhoto maps 422 Pydantic list detail to Validation with the msg`() = runTest {
        // FastAPI request-validation errors carry `detail` as a list of objects, not a string.
        val body = """{"detail":[{"loc":["body","carbs_low"],"msg":"value is not a valid number","type":"x"}]}"""
            .toResponseBody("application/json".toMediaType())
        coEvery { chatApi.uploadFoodPhoto(any<MultipartBody.Part>()) } returns Response.error(422, body)

        val e = repository.uploadPhoto(ByteArray(16)).exceptionOrNull()
        assertTrue(e is MealException.Validation)
        assertTrue(e!!.message!!.contains("not a valid number"))
    }

    @Test
    fun `uploadPhoto maps 400 to a try-a-different-photo message`() = runTest {
        coEvery { chatApi.uploadFoodPhoto(any<MultipartBody.Part>()) } returns
            Response.error(400, errorBody("Could not decode image."))

        val e = repository.uploadPhoto(ByteArray(16)).exceptionOrNull()
        assertTrue(e is MealException.EstimateFailed)
        assertTrue(e!!.message!!.contains("Could not decode", ignoreCase = true))
    }

    @Test
    fun `uploadPhoto maps 502 to a retryable vision-service message`() = runTest {
        coEvery { chatApi.uploadFoodPhoto(any<MultipartBody.Part>()) } returns
            Response.error(502, errorBody("AI vision service is unreachable."))

        val e = repository.uploadPhoto(ByteArray(16)).exceptionOrNull()
        assertTrue(e is MealException.EstimateFailed)
        assertTrue(e!!.message!!.contains("temporarily unavailable"))
    }

    @Test
    fun `uploadPhoto maps 500 to an honest server-error message, not an HTTP-code dump`() = runTest {
        // A truly unhandled backend 500 returns plain "Internal Server Error", not a FastAPI
        // {"detail":...} envelope -- the copy must still be honest and never echo "HTTP 500".
        coEvery { chatApi.uploadFoodPhoto(any<MultipartBody.Part>()) } returns
            Response.error(500, "Internal Server Error".toResponseBody("text/plain".toMediaType()))

        val e = repository.uploadPhoto(ByteArray(16)).exceptionOrNull()
        assertTrue(e is MealException.EstimateFailed)
        assertTrue(e!!.message!!.contains("on our end", ignoreCase = true))
        assertTrue(!e.message!!.contains("HTTP 500"))
    }

    @Test
    fun `uploadPhoto maps 503 to a temporarily-unavailable message`() = runTest {
        coEvery { chatApi.uploadFoodPhoto(any<MultipartBody.Part>()) } returns
            Response.error(503, errorBody("Could not save your meal estimate. Please try again."))

        val e = repository.uploadPhoto(ByteArray(16)).exceptionOrNull()
        assertTrue(e is MealException.EstimateFailed)
        assertTrue(e!!.message!!.contains("temporarily unavailable", ignoreCase = true))
    }

    @Test
    fun `uploadPhoto maps 504 to a took-too-long message`() = runTest {
        coEvery { chatApi.uploadFoodPhoto(any<MultipartBody.Part>()) } returns
            Response.error(504, errorBody("upstream request timed out"))

        val e = repository.uploadPhoto(ByteArray(16)).exceptionOrNull()
        assertTrue(e is MealException.EstimateFailed)
        assertTrue(e!!.message!!.contains("too long", ignoreCase = true))
    }

    @Test
    fun `a 5xx failure logs a diagnostic but a 4xx does not`() = runTest {
        val tree = RecordingTree()
        Timber.plant(tree)

        coEvery { chatApi.uploadFoodPhoto(any<MultipartBody.Part>()) } returns
            Response.error(500, "Internal Server Error".toResponseBody("text/plain".toMediaType()))
        repository.uploadPhoto(ByteArray(16))

        coEvery { chatApi.uploadFoodPhoto(any<MultipartBody.Part>()) } returns
            Response.error(404, errorBody("Meal intelligence is not enabled."))
        repository.uploadPhoto(ByteArray(16))

        // Exactly one diagnostic, for the 5xx; the expected 404 degradation stays quiet.
        assertEquals(1, tree.messages.size)
        assertTrue(tree.messages.first().contains("500"))
        assertTrue(tree.messages.first().contains("content-type=text/plain"))
    }

    @Test
    fun `probeAvailability surfaces FeatureDisabled when the flag is off`() = runTest {
        coEvery { api.listFoodRecords(any(), any()) } returns
            Response.error(404, errorBody("Meal intelligence is not enabled."))

        assertTrue(repository.probeAvailability().exceptionOrNull() is MealException.FeatureDisabled)
    }

    @Test
    fun `uploadPhoto maps 404 not-enabled to FeatureDisabled`() = runTest {
        coEvery { chatApi.uploadFoodPhoto(any<MultipartBody.Part>()) } returns
            Response.error(404, errorBody("Meal intelligence is not enabled."))

        assertTrue(
            repository.uploadPhoto(ByteArray(16)).exceptionOrNull() is MealException.FeatureDisabled,
        )
    }

    @Test
    fun `uploadPhoto maps 404 provider to NoAiProvider`() = runTest {
        coEvery { chatApi.uploadFoodPhoto(any<MultipartBody.Part>()) } returns
            Response.error(404, errorBody("No AI provider configured."))

        assertTrue(
            repository.uploadPhoto(ByteArray(16)).exceptionOrNull() is MealException.NoAiProvider,
        )
    }

    @Test
    fun `uploadPhoto maps 413 to ImageTooLarge`() = runTest {
        coEvery { chatApi.uploadFoodPhoto(any<MultipartBody.Part>()) } returns
            Response.error(413, errorBody("image exceeds 5242880 bytes"))

        assertTrue(
            repository.uploadPhoto(ByteArray(16)).exceptionOrNull() is MealException.ImageTooLarge,
        )
    }

    @Test
    fun `uploadPhoto maps 429 to RateLimited`() = runTest {
        coEvery { chatApi.uploadFoodPhoto(any<MultipartBody.Part>()) } returns
            Response.error(429, errorBody("rate limit exceeded"))

        assertTrue(
            repository.uploadPhoto(ByteArray(16)).exceptionOrNull() is MealException.RateLimited,
        )
    }

    @Test
    fun `listFoodRecords maps records`() = runTest {
        coEvery { api.listFoodRecords(any(), any()) } returns
            Response.success(FoodRecordListResponse(records = listOf(sampleRecord()), total = 1))

        val result = repository.listFoodRecords()

        assertTrue(result.isSuccess)
        assertEquals(1, result.getOrThrow().size)
        assertEquals("rec-1", result.getOrThrow().first().id)
    }

    @Test
    fun `listFoodRecords maps 404 not-enabled to FeatureDisabled`() = runTest {
        coEvery { api.listFoodRecords(any(), any()) } returns
            Response.error(404, errorBody("Meal intelligence is not enabled."))

        assertTrue(
            repository.listFoodRecords().exceptionOrNull() is MealException.FeatureDisabled,
        )
    }

    @Test
    fun `correctRecord returns the corrected record`() = runTest {
        coEvery { api.correctFoodRecord(any(), any()) } returns Response.success(
            sampleRecord(source = "user_corrected").copy(
                correctedCarbsLow = 45.0,
                correctedCarbsHigh = 60.0,
            ),
        )

        val result = repository.correctRecord("rec-1", 45.0, 60.0)

        assertTrue(result.isSuccess)
        assertTrue(result.getOrThrow().isCorrected)
    }

    @Test
    fun `saveAsCommonFood returns the saved baseline`() = runTest {
        coEvery { api.saveRecordAsCommonFood(any(), any()) } returns Response.success(
            CommonFoodResponse(
                id = "cf-1",
                name = "pasta",
                carbsLow = 45.0,
                carbsHigh = 60.0,
                createdAt = "2026-06-14T12:00:00Z",
                updatedAt = "2026-06-14T12:00:00Z",
            ),
        )

        val result = repository.saveAsCommonFood("rec-1", "pasta")

        assertTrue(result.isSuccess)
        assertEquals("pasta", result.getOrThrow().name)
    }

    @Test
    fun `updateCommonFood maps 409 to NameConflict`() = runTest {
        coEvery { api.updateCommonFood(any(), any()) } returns
            Response.error(409, errorBody("A common food with that name already exists."))

        assertTrue(
            repository.updateCommonFood("cf-1", name = "pasta").exceptionOrNull()
                is MealException.NameConflict,
        )
    }

    @Test
    fun `deleteFoodRecord succeeds on 204`() = runTest {
        coEvery { api.deleteFoodRecord(any()) } returns Response.success(Unit)

        assertTrue(repository.deleteFoodRecord("rec-1").isSuccess)
    }
}
