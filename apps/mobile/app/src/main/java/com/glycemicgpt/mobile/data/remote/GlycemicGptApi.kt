package com.glycemicgpt.mobile.data.remote

import com.glycemicgpt.mobile.data.remote.dto.AcknowledgeResponse
import com.glycemicgpt.mobile.data.remote.dto.AlertResponse
import com.glycemicgpt.mobile.data.remote.dto.AiProviderStatusResponse
import com.glycemicgpt.mobile.data.remote.dto.ChatRequest
import com.glycemicgpt.mobile.data.remote.dto.ChatResponse
import com.glycemicgpt.mobile.data.remote.dto.DeviceRegistrationRequest
import com.glycemicgpt.mobile.data.remote.dto.DeviceRegistrationResponse
import com.glycemicgpt.mobile.data.remote.dto.GlucoseRangeResponse
import com.glycemicgpt.mobile.data.remote.dto.SafetyLimitsResponse
import com.glycemicgpt.mobile.data.remote.dto.HealthResponse
import com.glycemicgpt.mobile.data.remote.dto.LoginRequest
import com.glycemicgpt.mobile.data.remote.dto.LoginResponse
import com.glycemicgpt.mobile.data.remote.dto.PumpPushRequest
import com.glycemicgpt.mobile.data.remote.dto.PumpPushResponse
import com.glycemicgpt.mobile.data.remote.dto.RefreshTokenRequest
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.POST
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

    // Glucose range settings
    @GET("/api/settings/target-glucose-range")
    suspend fun getGlucoseRange(): Response<GlucoseRangeResponse>

    // Safety limits settings
    @GET("/api/settings/safety-limits")
    suspend fun getSafetyLimits(): Response<SafetyLimitsResponse>
}
