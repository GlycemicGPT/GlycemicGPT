package com.glycemicgpt.mobile.data.repository

import android.content.Context
import com.glycemicgpt.mobile.BuildConfig
import com.glycemicgpt.mobile.data.auth.AuthManager
import com.glycemicgpt.mobile.data.local.AuthTokenStore
import com.glycemicgpt.mobile.data.local.GlucoseRangeStore
import com.glycemicgpt.mobile.data.local.SafetyLimitsStore
import com.glycemicgpt.mobile.data.remote.GlycemicGptApi
import com.glycemicgpt.mobile.data.remote.dto.LoginRequest
import com.glycemicgpt.mobile.service.AlertStreamService
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlin.coroutines.cancellation.CancellationException
import kotlin.math.roundToInt
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

data class LoginResult(
    val success: Boolean,
    val email: String? = null,
    val error: String? = null,
)

@Singleton
class AuthRepository @Inject constructor(
    @ApplicationContext private val appContext: Context,
    private val authTokenStore: AuthTokenStore,
    private val glucoseRangeStore: GlucoseRangeStore,
    private val safetyLimitsStore: SafetyLimitsStore,
    private val api: GlycemicGptApi,
    private val deviceRepository: DeviceRepository,
    private val authManager: AuthManager,
) {

    suspend fun testConnection(): Result<String> {
        return try {
            val response = api.healthCheck()
            if (response.isSuccessful) {
                Result.success("Connected successfully")
            } else {
                Result.failure(Exception("Server responded with HTTP ${response.code()}"))
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Timber.w(e, "Connection test failed")
            Result.failure(e)
        }
    }

    /**
     * Performs login and fires background tasks (device registration, glucose range fetch)
     * on the provided [scope]. Callers should pass their ViewModel's scope so these
     * fire-and-forget tasks are cancelled if the ViewModel is cleared.
     */
    suspend fun login(
        baseUrl: String,
        email: String,
        password: String,
        scope: CoroutineScope,
    ): LoginResult {
        if (baseUrl.isBlank()) {
            return LoginResult(success = false, error = "Configure server URL first")
        }
        if (!isValidUrl(baseUrl)) {
            return LoginResult(success = false, error = "Invalid server URL. HTTPS required.")
        }
        if (email.isBlank() || password.isBlank()) {
            return LoginResult(success = false, error = "Email and password are required")
        }
        return try {
            val response = api.login(LoginRequest(email = email, password = password))
            if (response.isSuccessful) {
                val body = response.body()
                    ?: return LoginResult(success = false, error = "Login failed: empty response from server")

                val expiresAtMs = System.currentTimeMillis() + (body.expiresIn * 1000L)
                authTokenStore.saveCredentials(baseUrl, body.accessToken, expiresAtMs, body.user.email)
                authTokenStore.saveRefreshToken(body.refreshToken)
                authManager.onLoginSuccess(scope)

                // Register device, fetch settings, and start alert stream
                scope.launch {
                    deviceRepository.registerDevice()
                        .onFailure { e -> Timber.w(e, "Device registration failed") }
                }
                scope.launch { fetchGlucoseRange() }
                scope.launch { fetchSafetyLimits() }
                AlertStreamService.start(appContext)

                LoginResult(success = true, email = body.user.email)
            } else {
                LoginResult(
                    success = false,
                    error = when (response.code()) {
                        401 -> "Invalid email or password"
                        else -> "Login failed: HTTP ${response.code()}"
                    },
                )
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Timber.w(e, "Login failed")
            LoginResult(success = false, error = "Network error: ${e.message ?: "Unknown error"}")
        }
    }

    fun logout(scope: CoroutineScope) {
        AlertStreamService.stop(appContext)
        // Clear token before async unregisterDevice -- unregistration is best-effort.
        // Server-side cleanup handles orphaned device registrations.
        authTokenStore.clearToken()
        safetyLimitsStore.clear()
        authManager.onLogout()
        scope.launch {
            deviceRepository.unregisterDevice()
                .onFailure { e -> Timber.w(e, "Device unregistration failed") }
        }
    }

    fun isValidUrl(url: String): Boolean {
        val parsed = url.toHttpUrlOrNull() ?: return false
        if (BuildConfig.DEBUG && parsed.scheme == "http") return true
        return parsed.scheme == "https"
    }

    fun saveBaseUrl(url: String) {
        authTokenStore.saveBaseUrl(url)
    }

    fun getBaseUrl(): String? = authTokenStore.getBaseUrl()

    /**
     * Returns true only if the access token is present AND not expired.
     * Prefer [hasActiveSession] for navigation/UI decisions -- this method
     * returns false when the access token is expired even if a valid refresh
     * token exists and the session can be restored.
     */
    fun isLoggedIn(): Boolean = authTokenStore.isLoggedIn()

    /**
     * Returns true if the user has an active session (valid refresh token),
     * regardless of whether the current access token has expired.
     * Use for navigation and UI state decisions.
     */
    fun hasActiveSession(): Boolean = authTokenStore.hasActiveSession()

    fun getUserEmail(): String? = authTokenStore.getUserEmail()

    suspend fun reRegisterDevice() {
        deviceRepository.registerDevice()
            .onFailure { e -> Timber.w(e, "Device re-registration failed") }
    }

    suspend fun refreshGlucoseRange() {
        fetchGlucoseRange()
    }

    suspend fun refreshSafetyLimits() {
        fetchSafetyLimits()
    }

    private suspend fun fetchGlucoseRange() {
        try {
            val response = api.getGlucoseRange()
            if (response.isSuccessful) {
                response.body()?.let { range ->
                    val ul = range.urgentLow.roundToInt()
                    val lo = range.lowTarget.roundToInt()
                    val hi = range.highTarget.roundToInt()
                    val uh = range.urgentHigh.roundToInt()
                    val allInRange = listOf(ul, lo, hi, uh).all { it in 20..500 }
                    if (!allInRange || !(ul < lo && lo < hi && hi < uh)) {
                        Timber.w("Glucose range invalid: %d/%d/%d/%d -- ignoring", ul, lo, hi, uh)
                        return
                    }
                    glucoseRangeStore.updateAll(ul, lo, hi, uh)
                    Timber.d("Glucose range fetched: %d/%d/%d/%d", ul, lo, hi, uh)
                }
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Timber.w(e, "Failed to fetch glucose range settings")
        }
    }

    private suspend fun fetchSafetyLimits() {
        try {
            val response = api.getSafetyLimits()
            if (response.isSuccessful) {
                response.body()?.let { limits ->
                    val min = limits.minGlucoseMgDl
                    val max = limits.maxGlucoseMgDl
                    val basal = limits.maxBasalRateMilliunits
                    val bolus = limits.maxBolusDoseMilliunits
                    if (min >= max || min !in 20..499 || max !in 21..500 || basal !in 1..15000 || bolus !in 1..25000) {
                        Timber.w("Safety limits invalid: min=%d max=%d basal=%d bolus=%d -- ignoring", min, max, basal, bolus)
                        return
                    }
                    safetyLimitsStore.updateAll(min, max, basal, bolus)
                    Timber.d("Safety limits synced: min=%d max=%d basal=%d bolus=%d", min, max, basal, bolus)
                }
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Timber.w(e, "Failed to fetch safety limits from backend")
        }
    }
}
