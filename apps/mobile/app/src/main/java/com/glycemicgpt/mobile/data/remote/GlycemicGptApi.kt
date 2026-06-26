package com.glycemicgpt.mobile.data.remote

import com.glycemicgpt.mobile.data.remote.dto.AcknowledgeResponse
import com.glycemicgpt.mobile.data.remote.dto.AlertResponse
import com.glycemicgpt.mobile.data.remote.dto.AiProviderStatusResponse
import com.glycemicgpt.mobile.data.remote.dto.AnalyticsConfigResponse
import com.glycemicgpt.mobile.data.remote.dto.PumpProfileResponse
import com.glycemicgpt.mobile.data.remote.dto.ChatRequest
import com.glycemicgpt.mobile.data.remote.dto.ChatResponse
import com.glycemicgpt.mobile.data.remote.dto.DeviceRegistrationRequest
import com.glycemicgpt.mobile.data.remote.dto.DeviceRegistrationResponse
import com.glycemicgpt.mobile.data.remote.dto.PluginDeclarationRequest
import com.glycemicgpt.mobile.data.remote.dto.GlucoseRangeResponse
import com.glycemicgpt.mobile.data.remote.dto.GlucoseUnitResponse
import com.glycemicgpt.mobile.data.remote.dto.GlucoseUnitUpdateRequest
import com.glycemicgpt.mobile.data.remote.dto.MealIntelligenceResponse
import com.glycemicgpt.mobile.data.remote.dto.MealIntelligenceUpdateRequest
import com.glycemicgpt.mobile.data.remote.dto.SafetyLimitsResponse
import com.glycemicgpt.mobile.data.remote.dto.HealthResponse
import com.glycemicgpt.mobile.data.remote.dto.LoginRequest
import com.glycemicgpt.mobile.data.remote.dto.LoginResponse
import com.glycemicgpt.mobile.data.remote.dto.PumpPushRequest
import com.glycemicgpt.mobile.data.remote.dto.NightscoutConnectionListDto
import com.glycemicgpt.mobile.data.remote.dto.NightscoutDataDto
import com.glycemicgpt.mobile.data.remote.dto.PumpPushResponse
import com.glycemicgpt.mobile.data.remote.dto.RefreshTokenRequest
import com.glycemicgpt.mobile.data.remote.dto.CommonFoodListResponse
import com.glycemicgpt.mobile.data.remote.dto.CommonFoodResponse
import com.glycemicgpt.mobile.data.remote.dto.CommonFoodUpdateRequest
import com.glycemicgpt.mobile.data.remote.dto.FoodRecordAuditResponse
import com.glycemicgpt.mobile.data.remote.dto.FoodRecordCorrectionRequest
import com.glycemicgpt.mobile.data.remote.dto.FoodRecordIdentityRequest
import com.glycemicgpt.mobile.data.remote.dto.FoodRecordListResponse
import com.glycemicgpt.mobile.data.remote.dto.FoodRecordResponse
import com.glycemicgpt.mobile.data.remote.dto.SaveAsCommonFoodRequest
import okhttp3.MultipartBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Query
import retrofit2.http.PUT
import retrofit2.http.Path

/**
 * Retrofit interface for the GlycemicGPT backend API.
 */
interface GlycemicGptApi {

    @GET("/health")
    suspend fun healthCheck(): Response<HealthResponse>

    @POST("/api/auth/mobile/login")
    suspend fun login(@Body request: LoginRequest): Response<LoginResponse>

    @POST("/api/auth/mobile/refresh")
    suspend fun refreshToken(@Body request: RefreshTokenRequest): Response<LoginResponse>

    @POST("/api/integrations/pump/push")
    suspend fun pushPumpEvents(@Body request: PumpPushRequest): Response<PumpPushResponse>

    @POST("/api/ai/chat")
    suspend fun sendChatMessage(@Body request: ChatRequest): Response<ChatResponse>

    @GET("/api/ai/provider")
    suspend fun getAiProvider(): Response<AiProviderStatusResponse>

    // Device registration (Story 16.11)
    @POST("/api/v1/devices/register")
    suspend fun registerDevice(@Body request: DeviceRegistrationRequest): Response<DeviceRegistrationResponse>

    @DELETE("/api/v1/devices/{deviceToken}")
    suspend fun unregisterDevice(@Path("deviceToken") deviceToken: String): Response<Unit>

    // Alert endpoints (Story 16.11)
    @GET("/api/v1/alerts/pending")
    suspend fun getPendingAlerts(): Response<List<AlertResponse>>

    @POST("/api/v1/alerts/{alertId}/acknowledge")
    suspend fun acknowledgeAlert(@Path("alertId") alertId: String): Response<AcknowledgeResponse>

    // Glucose display unit preference (per-account; backend exposes both GET and PATCH)
    @GET("/api/settings/glucose-unit")
    suspend fun getGlucoseUnit(): Response<GlucoseUnitResponse>

    @PATCH("/api/settings/glucose-unit")
    suspend fun patchGlucoseUnit(@Body request: GlucoseUnitUpdateRequest): Response<GlucoseUnitResponse>

    // Acknowledge the smart-default unit notice without changing the unit:
    // stamps source=user server-side so the notice never recurs.
    @POST("/api/settings/glucose-unit/acknowledge")
    suspend fun acknowledgeGlucoseUnitSeed(): Response<GlucoseUnitResponse>

    // Meal-intelligence feature preference (per-account; backend exposes GET and PATCH)
    @GET("/api/settings/meal-intelligence")
    suspend fun getMealIntelligence(): Response<MealIntelligenceResponse>

    @PATCH("/api/settings/meal-intelligence")
    suspend fun patchMealIntelligence(@Body request: MealIntelligenceUpdateRequest): Response<MealIntelligenceResponse>

    // Glucose range settings
    @GET("/api/settings/target-glucose-range")
    suspend fun getGlucoseRange(): Response<GlucoseRangeResponse>

    // Safety limits settings
    @GET("/api/settings/safety-limits")
    suspend fun getSafetyLimits(): Response<SafetyLimitsResponse>

    // Analytics configuration
    @GET("/api/settings/analytics-config")
    suspend fun getAnalyticsConfig(): Response<AnalyticsConfigResponse>

    // Pump profile summary
    @GET("/api/settings/pump-profile")
    suspend fun getPumpProfile(): Response<PumpProfileResponse>

    // Plugin declarations
    @PUT("/api/settings/plugin-declarations")
    suspend fun putPluginDeclarations(@Body body: PluginDeclarationRequest): Response<Unit>

    @DELETE("/api/settings/plugin-declarations")
    suspend fun deletePluginDeclarations(): Response<Unit>

    // Nightscout cloud-source plugin (Story 43.8): the mobile plugin pulls the
    // user's Nightscout-sourced data from the backend (the only Nightscout
    // client lives in the Python backend) and writes it into Room.
    @GET("/api/integrations/nightscout")
    suspend fun listNightscoutConnections(): Response<NightscoutConnectionListDto>

    @GET("/api/integrations/nightscout/{connectionId}/data")
    suspend fun getNightscoutData(
        @Path("connectionId") connectionId: String,
        @Query("since") since: String?,
        @Query("limit") limit: Int,
    ): Response<NightscoutDataDto>

    // Meal Intelligence (Epic 50). All endpoints return 404 when the
    // meal_intelligence_enabled feature flag is off; the upload returns 422 when
    // the user's AI provider has no vision route.
    @Multipart
    @POST("/api/food-records")
    suspend fun uploadFoodPhoto(@Part file: MultipartBody.Part): Response<FoodRecordResponse>

    @GET("/api/food-records")
    suspend fun listFoodRecords(
        @Query("limit") limit: Int = 50,
        @Query("offset") offset: Int = 0,
    ): Response<FoodRecordListResponse>

    @DELETE("/api/food-records/{recordId}")
    suspend fun deleteFoodRecord(@Path("recordId") recordId: String): Response<Unit>

    @POST("/api/food-records/{recordId}/correct")
    suspend fun correctFoodRecord(
        @Path("recordId") recordId: String,
        @Body request: FoodRecordCorrectionRequest,
    ): Response<FoodRecordResponse>

    // Food-identity confirmation (Story 50.H2): confirming/correcting *what the
    // food is* opens the grounding gate. Distinct from carb correction.
    @POST("/api/food-records/{recordId}/confirm-identity")
    suspend fun confirmFoodIdentity(
        @Path("recordId") recordId: String,
        @Body request: FoodRecordIdentityRequest,
    ): Response<FoodRecordResponse>

    // "How was this estimated" provenance trail (Story 50.H3). 404 until an
    // audit exists for the record.
    @GET("/api/food-records/{recordId}/audit")
    suspend fun getFoodRecordAudit(
        @Path("recordId") recordId: String,
    ): Response<FoodRecordAuditResponse>

    @POST("/api/food-records/{recordId}/save-as-common-food")
    suspend fun saveRecordAsCommonFood(
        @Path("recordId") recordId: String,
        @Body request: SaveAsCommonFoodRequest,
    ): Response<CommonFoodResponse>

    @GET("/api/common-foods")
    suspend fun listCommonFoods(
        @Query("limit") limit: Int = 50,
        @Query("offset") offset: Int = 0,
    ): Response<CommonFoodListResponse>

    @PATCH("/api/common-foods/{commonFoodId}")
    suspend fun updateCommonFood(
        @Path("commonFoodId") commonFoodId: String,
        @Body request: CommonFoodUpdateRequest,
    ): Response<CommonFoodResponse>

    @DELETE("/api/common-foods/{commonFoodId}")
    suspend fun deleteCommonFood(@Path("commonFoodId") commonFoodId: String): Response<Unit>
}
