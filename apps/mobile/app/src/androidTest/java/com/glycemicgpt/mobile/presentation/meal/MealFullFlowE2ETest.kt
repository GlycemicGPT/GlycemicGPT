package com.glycemicgpt.mobile.presentation.meal

import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTextReplacement
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.glycemicgpt.mobile.data.remote.GlycemicGptApi
import com.glycemicgpt.mobile.data.remote.dto.ChatRequest
import com.glycemicgpt.mobile.data.remote.dto.CommonFoodResponse
import com.glycemicgpt.mobile.data.remote.dto.CommonFoodUpdateRequest
import com.glycemicgpt.mobile.data.remote.dto.DeviceRegistrationRequest
import com.glycemicgpt.mobile.data.remote.dto.EstimateDispersionResponse
import com.glycemicgpt.mobile.data.remote.dto.FoodRecordCorrectionRequest
import com.glycemicgpt.mobile.data.remote.dto.FoodRecordIdentityRequest
import com.glycemicgpt.mobile.data.remote.dto.FoodRecordListResponse
import com.glycemicgpt.mobile.data.remote.dto.FoodRecordResponse
import com.glycemicgpt.mobile.data.remote.dto.LoginRequest
import com.glycemicgpt.mobile.data.remote.dto.PluginDeclarationRequest
import com.glycemicgpt.mobile.data.remote.dto.PumpPushRequest
import com.glycemicgpt.mobile.data.remote.dto.RefreshTokenRequest
import com.glycemicgpt.mobile.data.remote.dto.SaveAsCommonFoodRequest
import com.glycemicgpt.mobile.data.repository.MealRepository
import com.glycemicgpt.mobile.presentation.theme.GlycemicGptTheme
import com.squareup.moshi.Moshi
import kotlinx.coroutines.Dispatchers
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import retrofit2.Response
import java.io.File
import java.io.FileOutputStream
import java.util.UUID

/**
 * Full-flow meal-logging journey across screens (GJ1->GJ2->GJ3 + FM8), with the
 * backend faked at the Retrofit-API seam. Unlike the per-component Compose tests
 * (e.g. [CarbEstimateContentUiTest]), this drives the *real* screens and *real*
 * view models through a [NavHost]: capture -> result (qualifier present) ->
 * correct -> save-as-common-food -> history. Nothing here asserts an exact carb
 * value -- only that the structure and safety behavior a user depends on hold:
 * the never-dose qualifier is always on the estimate surface, a correction
 * persists through the flow, and an upload error never strands the spinner (the
 * FM8 stuck-spinner guard).
 *
 * The fake API is stateful so the cross-screen assertions are coherent (the
 * record saved on the result screen is the one history later lists).
 */
@RunWith(AndroidJUnit4::class)
class MealFullFlowE2ETest {

    @get:Rule
    val compose = createComposeRule()

    private val context: Context get() = ApplicationProvider.getApplicationContext()

    @Test
    fun fullFlow_capture_result_correct_save_history() {
        val api = FakeMealApi()
        setContentWithNav(api)
        awaitTag("meal_capture_camera") // probe resolved -> Ready (capture UI shown)

        // GJ1: capture -> estimate result. Drive the picked-image callback directly
        // (the system picker can't be fulfilled in a test) with a real decodable image.
        val photo = writeImage()
        runOnUi { mealLogVm.onImagePicked(Uri.fromFile(photo)) }
        awaitTag("meal_result_card")

        // The non-negotiable safety qualifier is present on the estimate surface,
        // and the estimate shows a carb range (not a lone number).
        compose.onNodeWithTag("meal_safety_qualifier", useUnmergedTree = true).assertIsDisplayed()
        compose.onNodeWithTag("meal_carb_range", useUnmergedTree = true).assertIsDisplayed()

        // GJ2: correct the estimate; the corrected note proves it persisted + re-rendered.
        tapInScroll("meal_correct_button")
        awaitTag("meal_correction_editor")
        compose.onNodeWithTag("meal_correct_low_input").performTextReplacement("70")
        compose.onNodeWithTag("meal_correct_high_input").performTextReplacement("80")
        // Editing the number fields raises the soft keyboard, which on a real emulator
        // overlays the inline Save button; dismiss it (as a user would) and scroll the
        // button into view so the click lands on the button, not the IME or the void
        // below a short screen's fold.
        dismissKeyboard()
        tapInScroll("meal_correct_save")
        awaitTag("meal_corrected_note")

        // GJ3: save the corrected estimate as a common food.
        tapInScroll("meal_save_common_button")
        awaitTag("meal_save_common_name_input")
        compose.onNodeWithTag("meal_save_common_name_input").performTextInput("Chicken Burrito")
        dismissKeyboard() // same IME-overlay guard before the dialog's confirm button
        compose.onNodeWithTag("meal_save_common_confirm").performClick()
        awaitTag("meal_saved_common_confirmation")
        check(api.commonFoods.isNotEmpty()) { "save-as-common-food never reached the API" }

        // Navigate to history (result -> idle -> History) and see the saved record.
        tapInScroll("meal_log_another")
        awaitTag("meal_history_button")
        tapInScroll("meal_history_button")
        awaitTag("meal_history_item")
        // The qualifier rides every estimate surface, history included.
        compose.onNodeWithTag("meal_safety_qualifier", useUnmergedTree = true).assertIsDisplayed()
    }

    @Test
    fun uploadError_neverLeavesSpinnerStuck_onUndecodableImage() {
        // The exact FM8 stuck-spinner bug: a photo that can't be decoded must
        // surface an error, never leave the estimate spinner running forever.
        val api = FakeMealApi()
        setContentSingle(api)
        awaitTag("meal_capture_camera")

        val notAnImage = File.createTempFile("e2e_meal_bad", ".txt", context.cacheDir)
            .apply { writeText("this is not an image") }
        runOnUi { mealLogVm.onImagePicked(Uri.fromFile(notAnImage)) }

        awaitTag("meal_error")
        compose.onAllNodesWithTag("meal_uploading", useUnmergedTree = true).assertCountEquals(0)
    }

    @Test
    fun uploadError_neverLeavesSpinnerStuck_onApiFailure() {
        // A backend failure mid-upload must also clear the spinner, not strand it.
        val api = FakeMealApi().apply { failUpload = true }
        setContentSingle(api)
        awaitTag("meal_capture_camera")

        val photo = writeImage()
        runOnUi { mealLogVm.onImagePicked(Uri.fromFile(photo)) }

        awaitTag("meal_error")
        compose.onAllNodesWithTag("meal_uploading", useUnmergedTree = true).assertCountEquals(0)
    }

    // ── Harness ──

    private lateinit var mealLogVm: MealLogViewModel
    private lateinit var historyVm: MealHistoryViewModel

    /** Build the real repository + view models against [api] (same instance for both API seams). */
    private fun buildViewModels(api: FakeMealApi) {
        val repository = MealRepository(api, api, Moshi.Builder().build())
        mealLogVm = MealLogViewModel(repository, context, Dispatchers.IO)
        historyVm = MealHistoryViewModel(repository)
    }

    /** Host the meal-log and history screens in a NavHost so navigation is exercised for real. */
    private fun setContentWithNav(api: FakeMealApi) {
        buildViewModels(api)
        compose.setContent {
            GlycemicGptTheme {
                val nav = rememberNavController()
                NavHost(navController = nav, startDestination = "log") {
                    composable("log") {
                        MealLogScreen(
                            onBack = {},
                            onNavigateToHistory = { nav.navigate("history") },
                            onNavigateToCommonFoods = {},
                            viewModel = mealLogVm,
                        )
                    }
                    composable("history") {
                        // A fresh hiltViewModel reloads on entry in production; mirror that
                        // by reloading the (shared) view model when this destination shows.
                        LaunchedEffect(Unit) { historyVm.load() }
                        MealHistoryScreen(onBack = { nav.popBackStack() }, viewModel = historyVm)
                    }
                }
            }
        }
    }

    /** Host only the meal-log screen (the FM8 stuck-spinner guards need no navigation). */
    private fun setContentSingle(api: FakeMealApi) {
        buildViewModels(api)
        compose.setContent {
            GlycemicGptTheme {
                MealLogScreen(
                    onBack = {},
                    onNavigateToHistory = {},
                    onNavigateToCommonFoods = {},
                    viewModel = mealLogVm,
                )
            }
        }
    }

    private fun runOnUi(block: () -> Unit) = compose.runOnUiThread(block)

    /** Hide the soft keyboard and wait for it to be gone, so it can't overlay a tap target. */
    private fun dismissKeyboard() = Espresso.closeSoftKeyboard()

    /**
     * Scroll a node in the result/idle scroll column into view, then click it. The result
     * surface is a [androidx.compose.foundation.verticalScroll] column, so on a shorter
     * screen a button can sit below the fold where a positional click would miss it.
     */
    private fun tapInScroll(tag: String) =
        compose.onNodeWithTag(tag).performScrollTo().performClick()

    private fun awaitTag(tag: String, timeoutMs: Long = 10_000) {
        compose.waitUntil(timeoutMs) {
            compose.onAllNodesWithTag(tag, useUnmergedTree = true).fetchSemanticsNodes().isNotEmpty()
        }
    }

    /** A small but genuinely decodable PNG written to the cache for the capture path. */
    private fun writeImage(): File {
        val bitmap = Bitmap.createBitmap(16, 16, Bitmap.Config.ARGB_8888)
        return File.createTempFile("e2e_meal", ".png", context.cacheDir).also { file ->
            FileOutputStream(file).use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
            bitmap.recycle()
        }
    }
}

/**
 * In-memory [GlycemicGptApi] for the meal flow. Only the food-record / common-food
 * endpoints the journey touches are implemented (statefully, so cross-screen reads
 * are coherent); every other endpoint is unreachable in this flow.
 */
@Suppress("TooManyFunctions") // Implements the full GlycemicGptApi; only the meal endpoints are live.
private class FakeMealApi : GlycemicGptApi {

    val records = mutableListOf<FoodRecordResponse>()
    val commonFoods = mutableListOf<CommonFoodResponse>()

    /** When set, the upload returns a 502 so the FM8 API-failure path can be exercised. */
    var failUpload = false

    override suspend fun uploadFoodPhoto(file: MultipartBody.Part): Response<FoodRecordResponse> {
        if (failUpload) return error502()
        val record = FoodRecordResponse(
            id = UUID.randomUUID().toString(),
            mealTimestamp = TS,
            foodDescription = "chicken burrito",
            carbsLow = 45.0,
            carbsHigh = 60.0,
            confidence = "low",
            source = "ai_estimate",
            createdAt = TS,
            estimateDispersion = EstimateDispersionResponse(
                note = "Reads of this photo varied somewhat -- treat this as approximate.",
                wideSpread = false,
                identityAgreement = true,
            ),
        )
        records.add(record)
        return Response.success(record)
    }

    override suspend fun listFoodRecords(limit: Int, offset: Int): Response<FoodRecordListResponse> =
        Response.success(FoodRecordListResponse(records = records.toList(), total = records.size))

    override suspend fun correctFoodRecord(
        recordId: String,
        request: FoodRecordCorrectionRequest,
    ): Response<FoodRecordResponse> {
        val index = records.indexOfFirst { it.id == recordId }
        if (index < 0) return error404()
        val corrected = records[index].copy(
            source = "user_corrected",
            correctedCarbsLow = request.correctedCarbsLow,
            correctedCarbsHigh = request.correctedCarbsHigh,
            correctedAt = TS,
        )
        records[index] = corrected
        return Response.success(corrected)
    }

    override suspend fun saveRecordAsCommonFood(
        recordId: String,
        request: SaveAsCommonFoodRequest,
    ): Response<CommonFoodResponse> {
        val record = records.firstOrNull { it.id == recordId } ?: return error404()
        val common = CommonFoodResponse(
            id = UUID.randomUUID().toString(),
            name = request.name,
            // Prefer the corrected value, like the backend's promotion does.
            carbsLow = record.correctedCarbsLow ?: record.carbsLow,
            carbsHigh = record.correctedCarbsHigh ?: record.carbsHigh,
            createdAt = TS,
            updatedAt = TS,
        )
        commonFoods.add(common)
        return Response.success(common)
    }

    private fun <T> error502(): Response<T> =
        Response.error(502, "{\"detail\":\"AI vision service unavailable\"}".toResponseBody(JSON))

    private fun <T> error404(): Response<T> =
        Response.error(404, "{\"detail\":\"Food record not found.\"}".toResponseBody(JSON))

    // Endpoints outside the journey under test are never invoked here.
    override suspend fun healthCheck() = notUsed()
    override suspend fun login(request: LoginRequest) = notUsed()
    override suspend fun refreshToken(request: RefreshTokenRequest) = notUsed()
    override suspend fun pushPumpEvents(request: PumpPushRequest) = notUsed()
    override suspend fun sendChatMessage(request: ChatRequest) = notUsed()
    override suspend fun getAiProvider() = notUsed()
    override suspend fun registerDevice(request: DeviceRegistrationRequest) = notUsed()
    override suspend fun unregisterDevice(deviceToken: String) = notUsed()
    override suspend fun getPendingAlerts() = notUsed()
    override suspend fun acknowledgeAlert(alertId: String) = notUsed()
    override suspend fun getGlucoseRange() = notUsed()
    override suspend fun getSafetyLimits() = notUsed()
    override suspend fun getAnalyticsConfig() = notUsed()
    override suspend fun getPumpProfile() = notUsed()
    override suspend fun putPluginDeclarations(body: PluginDeclarationRequest) = notUsed()
    override suspend fun deletePluginDeclarations() = notUsed()
    override suspend fun listNightscoutConnections() = notUsed()
    override suspend fun getNightscoutData(connectionId: String, since: String?, limit: Int) = notUsed()
    override suspend fun deleteFoodRecord(recordId: String) = notUsed()
    override suspend fun confirmFoodIdentity(recordId: String, request: FoodRecordIdentityRequest) = notUsed()
    override suspend fun getFoodRecordAudit(recordId: String) = notUsed()
    override suspend fun listCommonFoods(limit: Int, offset: Int) = notUsed()
    override suspend fun updateCommonFood(commonFoodId: String, request: CommonFoodUpdateRequest) = notUsed()
    override suspend fun deleteCommonFood(commonFoodId: String) = notUsed()

    private fun notUsed(): Nothing =
        throw UnsupportedOperationException("Endpoint not used in the meal full-flow test")

    private companion object {
        const val TS = "2026-06-18T05:00:00Z"
        val JSON = "application/json".toMediaType()
    }
}
