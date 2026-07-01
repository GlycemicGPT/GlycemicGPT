package com.glycemicgpt.mobile.data.repository

import android.content.Context
import com.glycemicgpt.mobile.BuildConfig
import com.glycemicgpt.mobile.data.auth.AuthManager
import com.glycemicgpt.mobile.data.local.AnalyticsSettingsStore
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.local.AuthTokenStore
import com.glycemicgpt.mobile.data.local.GlucoseRangeStore
import com.glycemicgpt.mobile.data.local.PumpProfileStore
import com.glycemicgpt.mobile.data.local.SafetyLimitsStore
import com.glycemicgpt.mobile.data.remote.GlycemicGptApi
import com.glycemicgpt.mobile.data.remote.UrlSecurityPolicy
import com.glycemicgpt.mobile.data.remote.dto.GlucoseUnitUpdateRequest
import com.glycemicgpt.mobile.data.remote.dto.LoginRequest
import com.glycemicgpt.mobile.data.remote.dto.MealIntelligenceUpdateRequest
import com.glycemicgpt.mobile.domain.model.GlucoseUnit
import com.glycemicgpt.mobile.service.AlertStreamService
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlin.coroutines.cancellation.CancellationException
import kotlin.math.roundToInt
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/** Backend glucose-unit provenance wire value flagging a still-unconfirmed smart default. */
private const val GLUCOSE_UNIT_SOURCE_SEED = "seed"

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
    private val analyticsSettingsStore: AnalyticsSettingsStore,
    private val pumpProfileStore: PumpProfileStore,
    private val appSettingsStore: AppSettingsStore,
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
            return LoginResult(success = false, error = UrlSecurityPolicy.INVALID_URL_MESSAGE)
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
                scope.launch { fetchGlucoseUnit() }
                scope.launch { fetchMealIntelligence() }
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
        analyticsSettingsStore.clear()
        pumpProfileStore.clear()
        // The glucose unit is a per-account preference; reset to the neutral default so a stale
        // unit can't carry over to the next account before its reconcile lands.
        appSettingsStore.glucoseUnit = GlucoseUnit.MGDL
        appSettingsStore.glucoseUnitSeedPending = false
        // Meal intelligence is per-account; reset to the default (ON) so a stale
        // value can't carry over to the next account before its reconcile lands.
        appSettingsStore.mealIntelligenceEnabled = true
        authManager.onLogout()
        scope.launch {
            deviceRepository.unregisterDevice()
                .onFailure { e -> Timber.w(e, "Device unregistration failed") }
        }
    }

    /**
     * The single chokepoint for server-URL transport policy: `https` always, `http` only in a
     * debug build or when the user has opted into insecure LAN HTTP AND the host is a private/LAN
     * literal. All three entry points (onboarding test, settings save, login) route through here.
     */
    fun isValidUrl(url: String): Boolean =
        UrlSecurityPolicy.isAllowed(
            url = url,
            isDebug = BuildConfig.DEBUG,
            allowInsecureLanHttp = appSettingsStore.allowInsecureLanHttp,
        )

    /**
     * True when [url] is rejected today only because insecure LAN HTTP is off -- i.e. `http://` to
     * a private host on a non-debug build. The UI uses this to offer a one-tap opt-in rather than a
     * dead-end error.
     */
    fun isBlockedPendingLanHttpOptIn(url: String): Boolean =
        !isValidUrl(url) && UrlSecurityPolicy.isBlockedPendingLanOptIn(url, BuildConfig.DEBUG)

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

    /** Reconcile the cached glucose display unit from the backend (the account is the source of truth). */
    suspend fun refreshGlucoseUnit() {
        fetchGlucoseUnit()
    }

    /** Reconcile the cached meal-intelligence preference from the backend (the account is the source of truth). */
    suspend fun refreshMealIntelligence() {
        fetchMealIntelligence()
    }

    /**
     * Write the user's meal-intelligence preference to the account
     * (`PATCH /api/settings/meal-intelligence`) and reconcile the local cache to
     * whatever the server returns. The preference is per-account, so this -- not the
     * local cache -- is what gates the meal surfaces consistently across web, phone,
     * and watch. On failure the optimistic local cache is left intact (the next
     * reconcile corrects it); the [Result] lets the caller surface a transient error.
     */
    suspend fun updateMealIntelligence(enabled: Boolean): Result<Boolean> {
        return try {
            val response = api.patchMealIntelligence(MealIntelligenceUpdateRequest(enabled = enabled))
            if (response.isSuccessful) {
                val resolved = response.body()?.enabled ?: enabled
                appSettingsStore.mealIntelligenceEnabled = resolved
                Result.success(resolved)
            } else {
                if (response.code() == 401 || response.code() == 403) {
                    // The account is forbidden this setting (e.g. caregiver 403) or
                    // unauthenticated: fail closed so meal surfaces don't stay on.
                    appSettingsStore.mealIntelligenceEnabled = false
                }
                Result.failure(Exception("Server responded with HTTP ${response.code()}"))
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Timber.w(e, "Failed to update meal intelligence preference")
            Result.failure(e)
        }
    }

    /**
     * Write the user's glucose display unit to the account (`PATCH /api/settings/glucose-unit`)
     * and reconcile the local cache to whatever the server returns. The unit is a per-account
     * preference, so this -- not the local cache -- is what makes it consistent across web,
     * phone, watch, and AI text. On failure the optimistic local cache is left intact (the next
     * reconcile will correct it); the [Result] lets the caller surface a transient error.
     */
    suspend fun updateGlucoseUnit(unit: GlucoseUnit): Result<GlucoseUnit> {
        return try {
            val response = api.patchGlucoseUnit(GlucoseUnitUpdateRequest(glucoseUnit = unit.wireValue))
            if (response.isSuccessful) {
                val resolved = response.body()?.let { GlucoseUnit.fromWire(it.glucoseUnit) } ?: unit
                appSettingsStore.glucoseUnit = resolved
                // An explicit choice confirms the preference, so the one-time smart-default
                // notice must not show (the backend also flips provenance to "user").
                appSettingsStore.glucoseUnitSeedPending = false
                Result.success(resolved)
            } else {
                Result.failure(Exception("Server responded with HTTP ${response.code()}"))
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Timber.w(e, "Failed to update glucose unit")
            Result.failure(e)
        }
    }

    /**
     * Acknowledge the smart-default glucose-unit notice without changing the unit.
     * Stamps provenance `source=user` server-side -- so the notice never recurs and a later seed
     * never re-fires -- and clears the local pending flag. Used when the user dismisses the notice
     * without picking a unit; picking one goes through [updateGlucoseUnit], which already confirms.
     */
    suspend fun acknowledgeGlucoseUnitSeed(): Result<Unit> {
        return try {
            val response = api.acknowledgeGlucoseUnitSeed()
            if (response.isSuccessful) {
                appSettingsStore.glucoseUnitSeedPending = false
                Result.success(Unit)
            } else {
                Result.failure(Exception("Server responded with HTTP ${response.code()}"))
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Timber.w(e, "Failed to acknowledge glucose unit seed")
            Result.failure(e)
        }
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

    private suspend fun fetchGlucoseUnit() {
        try {
            val response = api.getGlucoseUnit()
            if (response.isSuccessful) {
                response.body()?.let { body ->
                    val unit = GlucoseUnit.fromWire(body.glucoseUnit)
                    appSettingsStore.glucoseUnit = unit
                    // A still-seed-owned non-mgdl preference drives the one-time smart-default
                    // confirmation notice in Settings. Reconcile clears it once the
                    // account provenance is "user" (the user confirmed elsewhere).
                    appSettingsStore.glucoseUnitSeedPending =
                        body.glucoseUnitSource == GLUCOSE_UNIT_SOURCE_SEED &&
                        unit != GlucoseUnit.MGDL
                    Timber.d(
                        "Glucose unit reconciled: %s (source=%s)",
                        body.glucoseUnit,
                        body.glucoseUnitSource,
                    )
                }
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            // Keep the cached unit (ultimately MGDL) on any failure.
            Timber.w(e, "Failed to fetch glucose unit preference")
        }
    }

    private suspend fun fetchMealIntelligence() {
        try {
            val response = api.getMealIntelligence()
            if (response.isSuccessful) {
                response.body()?.let { body ->
                    appSettingsStore.mealIntelligenceEnabled = body.enabled
                    Timber.d("Meal intelligence reconciled: %b", body.enabled)
                }
            } else if (response.code() == 401 || response.code() == 403) {
                // The account is forbidden this setting (e.g. caregiver 403) or the
                // session expired: fail closed so a cached/default-ON value can't
                // leave meal surfaces visible for an account the backend rejects.
                appSettingsStore.mealIntelligenceEnabled = false
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            // Keep the cached value (ultimately the default ON) on a transient/network failure.
            Timber.w(e, "Failed to fetch meal intelligence preference")
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
