package com.glycemicgpt.mobile.data.auth

import com.glycemicgpt.mobile.data.local.AuthTokenStore
import com.glycemicgpt.mobile.data.remote.dto.LoginResponse
import com.glycemicgpt.mobile.data.remote.dto.RefreshTokenRequest
import com.squareup.moshi.Moshi
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Manages authentication state and proactive token refresh.
 *
 * Responsibilities:
 * - Exposes observable [AuthState] via [authState]
 * - Validates tokens on startup
 * - Proactively refreshes access tokens before expiry
 * - Handles refresh failures gracefully (emits [AuthState.Expired])
 *
 * Thread safety: [performRefresh] is protected by a [Mutex] to prevent
 * concurrent refresh attempts (e.g., proactive timer + interceptor 401).
 */
@Singleton
class AuthManager @Inject constructor(
    private val authTokenStore: AuthTokenStore,
    private val refreshClientProvider: RefreshClientProvider,
    private val moshi: Moshi,
) {
    /** Dispatcher for blocking IO operations. Overridable for testing. */
    var ioDispatcher: CoroutineDispatcher = Dispatchers.IO

    private val _authState = MutableStateFlow<AuthState>(AuthState.Unauthenticated)
    val authState: StateFlow<AuthState> = _authState.asStateFlow()

    private var refreshJob: Job? = null
    private val refreshMutex = Mutex()
    /** Retained scope for scheduling proactive refreshes from non-coroutine contexts. */
    @Volatile
    private var retainedScope: CoroutineScope? = null

    /**
     * Validates stored tokens on startup and schedules proactive refresh.
     * Call this from Application.onCreate() or the first ViewModel that loads.
     */
    fun validateOnStartup(scope: CoroutineScope) {
        retainedScope = scope
        val refreshToken = authTokenStore.getRefreshToken()
        if (refreshToken == null) {
            _authState.value = AuthState.Unauthenticated
            return
        }

        // Check if refresh token is expired
        if (authTokenStore.isRefreshTokenExpired()) {
            Timber.w("Refresh token expired on startup")
            _authState.value = AuthState.Expired()
            return
        }

        val accessToken = authTokenStore.getToken()
        if (accessToken != null) {
            // Valid access token exists
            _authState.value = AuthState.Authenticated
            scheduleProactiveRefresh(scope)
            return
        }

        // Access token expired but refresh token is valid -- attempt refresh with retry
        _authState.value = AuthState.Refreshing
        scope.launch {
            performRefreshWithRetry(scope)
        }
    }

    /**
     * Schedules a coroutine that refreshes the access token before it expires.
     * Re-schedules itself after each successful refresh.
     */
    fun scheduleProactiveRefresh(scope: CoroutineScope) {
        refreshJob?.cancel()
        refreshJob = scope.launch {
            val expiresAt = authTokenStore.getTokenExpiresAtMs()
            if (expiresAt <= 0) return@launch

            val refreshAt = expiresAt - AuthTokenStore.PROACTIVE_REFRESH_WINDOW_MS
            val delayMs = (refreshAt - System.currentTimeMillis()).coerceAtLeast(0)

            Timber.d("Proactive refresh scheduled in ${delayMs / 1000}s")
            delay(delayMs)

            performRefresh(scope)
        }
    }

    /**
     * Attempts to refresh the access token using the stored refresh token.
     * Updates [authState] based on the result.
     *
     * Protected by [refreshMutex] to prevent concurrent refresh attempts.
     * Runs the blocking OkHttp call on [Dispatchers.IO].
     */
    suspend fun performRefresh(scope: CoroutineScope) {
        refreshMutex.withLock {
            // Re-check after acquiring the lock -- another coroutine may have refreshed already
            val existingToken = authTokenStore.getToken()
            if (existingToken != null && _authState.value is AuthState.Authenticated) {
                return
            }

            val refreshToken = authTokenStore.getRefreshToken()
            if (refreshToken == null) {
                _authState.value = AuthState.Unauthenticated
                return
            }

            if (authTokenStore.isRefreshTokenExpired()) {
                Timber.w("Refresh token expired, cannot refresh")
                _authState.value = AuthState.Expired()
                return
            }

            val baseUrl = authTokenStore.getBaseUrl()
            if (baseUrl.isNullOrBlank()) {
                Timber.w("No base URL configured, cannot refresh")
                _authState.value = AuthState.Expired()
                return
            }

            _authState.value = AuthState.Refreshing

            try {
                val body = RefreshTokenRequest(refreshToken = refreshToken)
                val adapter = moshi.adapter(RefreshTokenRequest::class.java)
                val json = adapter.toJson(body)

                val request = Request.Builder()
                    .url("http://localhost/api/auth/mobile/refresh")
                    .post(json.toRequestBody("application/json".toMediaType()))
                    .build()

                val response = withContext(ioDispatcher) {
                    refreshClientProvider.refreshClient.newCall(request).execute()
                }

                response.use { resp ->
                    if (resp.isSuccessful) {
                        val responseBody = resp.body?.string()
                        if (responseBody == null) {
                            Timber.w("Refresh response body is null")
                            _authState.value = AuthState.Expired()
                            return
                        }

                        val loginAdapter = moshi.adapter(LoginResponse::class.java)
                        val loginResponse = loginAdapter.fromJson(responseBody)
                        if (loginResponse == null) {
                            Timber.w("Failed to parse refresh response")
                            _authState.value = AuthState.Expired()
                            return
                        }

                        val expiresAtMs = System.currentTimeMillis() + (loginResponse.expiresIn * 1000L)
                        authTokenStore.saveCredentials(
                            baseUrl,
                            loginResponse.accessToken,
                            expiresAtMs,
                            loginResponse.user.email,
                        )
                        authTokenStore.saveRefreshToken(loginResponse.refreshToken)

                        Timber.d("Proactive token refresh succeeded")
                        _authState.value = AuthState.Authenticated
                        scheduleProactiveRefresh(scope)
                    } else if (resp.code == 401 || resp.code == 403) {
                        // Definitive auth rejection -- refresh token is invalid/revoked
                        Timber.w("Token refresh rejected with HTTP ${resp.code}, clearing session")
                        authTokenStore.clearToken()
                        _authState.value = AuthState.Expired()
                    } else {
                        // Transient server error (5xx, etc.) -- preserve tokens for retry
                        Timber.w("Token refresh got HTTP ${resp.code}, preserving session for retry")
                        val currentToken = authTokenStore.getRawToken()
                        if (currentToken != null) {
                            // We still have a (possibly expired) access token -- mark authenticated
                            // so the app can function, and schedule proactive retry
                            _authState.value = AuthState.Authenticated
                            scheduleProactiveRefresh(scope)
                        }
                        // If no access token, leave state as Refreshing so
                        // performRefreshWithRetry can attempt again on startup
                    }
                }
            } catch (e: CancellationException) {
                throw e // Never swallow coroutine cancellation
            } catch (e: Exception) {
                Timber.w(e, "Proactive token refresh failed")
                // Network error -- don't clear tokens, stay authenticated if we had a valid token
                val currentToken = authTokenStore.getRawToken()
                if (currentToken != null) {
                    _authState.value = AuthState.Authenticated
                    // Retry later
                    scheduleProactiveRefresh(scope)
                } else {
                    _authState.value = AuthState.Expired()
                }
            }
        }
    }

    /**
     * Attempts refresh with retry for startup scenarios where a transient network
     * failure shouldn't immediately destroy the session.
     *
     * Checks for actual token acquisition (not just auth state) to determine
     * whether to retry, since transient 5xx errors leave state as [AuthState.Refreshing].
     */
    private suspend fun performRefreshWithRetry(
        scope: CoroutineScope,
        maxAttempts: Int = 3,
    ) {
        for (attempt in 0 until maxAttempts) {
            performRefresh(scope)

            // Success: we obtained a valid access token
            if (authTokenStore.getToken() != null) return

            // Definitive failure: no point retrying
            val state = _authState.value
            if (state is AuthState.Expired || state is AuthState.Unauthenticated) return

            // Transient failure (Refreshing state) -- retry with backoff
            if (attempt < maxAttempts - 1) {
                val backoffMs = 1000L * (1 shl attempt) // 1s, 2s
                Timber.d("Startup refresh attempt ${attempt + 1} failed transiently, retrying in ${backoffMs}ms")
                delay(backoffMs)
            }
        }

        // All attempts exhausted without obtaining a token
        if (authTokenStore.getToken() == null && _authState.value !is AuthState.Expired) {
            Timber.w("Startup refresh exhausted all attempts without obtaining a token")
            _authState.value = AuthState.Expired()
        }
    }

    /** Called after a successful login to set the authenticated state. */
    fun onLoginSuccess(scope: CoroutineScope) {
        // Prefer the app-lifetime scope set by validateOnStartup() over the
        // caller-provided scope (which is often a ViewModel scope that dies
        // when the UI is torn down, breaking proactive refresh scheduling).
        val effectiveScope = retainedScope ?: scope.also { retainedScope = it }
        _authState.value = AuthState.Authenticated
        scheduleProactiveRefresh(effectiveScope)
    }

    /** Called on logout to reset state. */
    fun onLogout() {
        refreshJob?.cancel()
        refreshJob = null
        retainedScope = null
        _authState.value = AuthState.Unauthenticated
    }

    /** Called by TokenRefreshInterceptor when a refresh attempt fails. */
    fun onRefreshFailed() {
        refreshJob?.cancel()
        _authState.value = AuthState.Expired()
    }

    /** Called by TokenRefreshInterceptor after a successful interceptor-driven refresh. */
    fun onInterceptorRefreshSuccess() {
        // Guard against a late interceptor callback racing with logout
        if (_authState.value is AuthState.Unauthenticated) {
            Timber.w("Ignoring interceptor refresh success after logout")
            return
        }
        _authState.value = AuthState.Authenticated
        val scope = retainedScope
        if (scope?.isActive == true) {
            scheduleProactiveRefresh(scope)
        } else {
            Timber.w("Skipping proactive refresh scheduling: retained scope unavailable or inactive")
        }
    }
}
