package com.glycemicgpt.mobile.data.remote

import com.glycemicgpt.mobile.data.auth.AuthManager
import com.glycemicgpt.mobile.data.auth.RefreshClientProvider
import com.glycemicgpt.mobile.data.local.AuthTokenStore
import com.glycemicgpt.mobile.data.remote.dto.LoginResponse
import com.glycemicgpt.mobile.data.remote.dto.RefreshTokenRequest
import com.squareup.moshi.Moshi
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Provider
import javax.inject.Singleton

/**
 * OkHttp Interceptor that transparently refreshes expired access tokens.
 *
 * When a request receives a 401 response and a refresh token is available,
 * this interceptor:
 * 1. Checks if the refresh token is still valid
 * 2. Calls the /api/auth/mobile/refresh endpoint (using a separate OkHttpClient)
 * 3. On success: saves new tokens, notifies AuthManager, and retries the original request
 * 4. On failure: clears tokens, notifies AuthManager of session expiry
 *
 * Uses synchronized block to prevent concurrent refresh attempts.
 */
@Singleton
class TokenRefreshInterceptor @Inject constructor(
    private val authTokenStore: AuthTokenStore,
    private val refreshClientProvider: RefreshClientProvider,
    private val moshi: Moshi,
    // Use Provider to break circular dependency (AuthManager -> this -> AuthManager)
    private val authManagerProvider: Provider<AuthManager>,
) : Interceptor {

    private val lock = Any()

    override fun intercept(chain: Interceptor.Chain): Response {
        val original = chain.request()
        val response = chain.proceed(original)

        // Only attempt refresh on 401 responses
        if (response.code != 401) return response

        // Don't try to refresh the refresh endpoint itself
        if (original.url.encodedPath.contains("/api/auth/mobile/refresh")) return response

        val refreshToken = authTokenStore.getRefreshToken() ?: return response

        // Check if refresh token is expired before attempting
        if (authTokenStore.isRefreshTokenExpired()) {
            Timber.w("Refresh token expired, cannot auto-refresh")
            authTokenStore.clearToken()
            authManagerProvider.get().onRefreshFailed()
            return response
        }

        synchronized(lock) {
            // Double-check: another thread may have already refreshed
            val currentToken = authTokenStore.getRawToken()
            val originalAuth = original.header("Authorization")
            val originalToken = originalAuth?.removePrefix("Bearer ")
            if (currentToken != null && originalToken != null && currentToken != originalToken) {
                // Token was already refreshed by another thread; retry with new token
                response.close()
                val retryRequest = original.newBuilder()
                    .header("Authorization", "Bearer $currentToken")
                    .build()
                return chain.proceed(retryRequest)
            }

            // Attempt token refresh
            val newAccessToken = performRefresh(refreshToken)
            if (newAccessToken != null) {
                response.close()
                val retryRequest = original.newBuilder()
                    .header("Authorization", "Bearer $newAccessToken")
                    .build()
                return chain.proceed(retryRequest)
            }
        }

        return response
    }

    /**
     * Calls the refresh endpoint and saves new tokens on success.
     * Returns the new access token, or null on failure.
     */
    private fun performRefresh(refreshToken: String): String? {
        val baseUrl = authTokenStore.getBaseUrl()
        if (baseUrl.isNullOrBlank()) {
            Timber.w("No base URL configured, cannot refresh via interceptor")
            authManagerProvider.get().onRefreshFailed()
            return null
        }

        return try {
            val body = RefreshTokenRequest(refreshToken = refreshToken)
            val adapter = moshi.adapter(RefreshTokenRequest::class.java)
            val json = adapter.toJson(body)

            val request = Request.Builder()
                .url("http://localhost/api/auth/mobile/refresh") // BaseUrlInterceptor rewrites this
                .post(json.toRequestBody("application/json".toMediaType()))
                .build()

            val refreshResponse = refreshClientProvider.refreshClient.newCall(request).execute()

            refreshResponse.use { resp ->
                if (resp.isSuccessful) {
                    val responseBody = resp.body?.string() ?: return null
                    val loginAdapter = moshi.adapter(LoginResponse::class.java)
                    val loginResponse = loginAdapter.fromJson(responseBody) ?: return null

                    val expiresAtMs = System.currentTimeMillis() + (loginResponse.expiresIn * 1000L)
                    authTokenStore.saveCredentials(
                        baseUrl,
                        loginResponse.accessToken,
                        expiresAtMs,
                        loginResponse.user.email,
                    )
                    authTokenStore.saveRefreshToken(loginResponse.refreshToken)

                    Timber.d("Token refreshed successfully via interceptor")
                    authManagerProvider.get().onInterceptorRefreshSuccess(
                        kotlinx.coroutines.MainScope(),
                    )
                    loginResponse.accessToken
                } else if (resp.code == 401 || resp.code == 403) {
                    // Definitive auth rejection -- refresh token is invalid/revoked
                    Timber.w("Token refresh rejected with HTTP ${resp.code}, clearing session")
                    authTokenStore.clearToken()
                    authManagerProvider.get().onRefreshFailed()
                    null
                } else {
                    // Transient server error (5xx, etc.) -- preserve tokens for retry
                    Timber.w("Token refresh got HTTP ${resp.code}, preserving session for retry")
                    null
                }
            }
        } catch (e: java.io.IOException) {
            // Network error -- preserve tokens; connectivity will return
            Timber.w(e, "Token refresh failed due to network error, preserving session")
            null
        }
    }
}
