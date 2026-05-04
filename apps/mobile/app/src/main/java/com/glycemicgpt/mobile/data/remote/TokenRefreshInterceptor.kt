package com.glycemicgpt.mobile.data.remote

import com.glycemicgpt.mobile.data.auth.AuthManager
import com.glycemicgpt.mobile.data.local.AuthTokenStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import okhttp3.Interceptor
import okhttp3.Response
import timber.log.Timber
import java.io.IOException
import javax.inject.Inject
import javax.inject.Provider
import javax.inject.Singleton

/**
 * OkHttp interceptor that transparently refreshes expired access tokens.
 *
 * On a 401 response we delegate the actual refresh to
 * [AuthManager.refreshForInterceptor], which serializes with the proactive
 * refresh timer through a single mutex. This is the bug fix for issue #520:
 * the previous implementation kept its own [Object] monitor that did not
 * coordinate with the proactive timer, and used the original request's
 * Authorization header to detect "another thread already refreshed" --
 * which is null when the access token was already expired before the
 * request was sent, so every queued 401 in a burst would fall through to
 * a fresh refresh and replay the previous refresh token against the
 * server's replay detector.
 *
 * The new flow:
 *   1. Get a 401 from a non-refresh endpoint
 *   2. Verify a refresh token exists and is not itself expired
 *   3. Call [AuthManager.refreshForInterceptor] (single mutex, single
 *      source of truth for refresh state). Pass the original request's
 *      auth token so the manager can distinguish "already refreshed"
 *      from "this exact token was just rejected".
 *   4. Retry the original request with the returned access token
 */
@Singleton
class TokenRefreshInterceptor @Inject constructor(
    private val authTokenStore: AuthTokenStore,
    // Use Provider to break circular dependency (AuthManager -> this -> AuthManager)
    private val authManagerProvider: Provider<AuthManager>,
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val original = chain.request()
        val response = chain.proceed(original)

        // Only attempt refresh on 401 responses
        if (response.code != 401) return response

        // Don't try to refresh the refresh endpoint itself
        if (original.url.encodedPath.contains("/api/auth/mobile/refresh")) return response

        // Need a refresh token to do anything
        if (authTokenStore.getRefreshToken() == null) return response

        // Resolve the AuthManager once. The Hilt Provider's get() should be
        // cheap, but we're in the request hot path so avoid repeating it.
        val authManager = authManagerProvider.get()

        // If the refresh token itself is expired, the session is dead. Clear
        // and notify -- no point hitting the server.
        if (authTokenStore.isRefreshTokenExpired()) {
            Timber.w("Refresh token expired, cannot auto-refresh")
            authTokenStore.clearToken()
            authManager.onRefreshFailed()
            return response
        }

        // Capture the access token the original request actually carried so
        // AuthManager can decide whether the refresh has already happened
        // for us, or whether THIS exact token was just rejected.
        val originalToken = original.header("Authorization")?.removePrefix("Bearer ")

        // Delegate the refresh itself to AuthManager. Serialized via the
        // shared mutex with proactive refreshes, and short-circuits when
        // another caller already produced a valid access token.
        //
        // runBlocking is correct here: OkHttp interceptors run on the
        // dispatcher's worker thread (not a coroutine context), and we
        // need to return synchronously to the chain.
        //
        // CancellationException is translated to IOException so OkHttp
        // callers see a recognized failure mode instead of an unchecked
        // throwable.
        val newAccessToken = try {
            runBlocking {
                authManager.refreshForInterceptor(originalToken)
            }
        } catch (e: CancellationException) {
            throw IOException("Token refresh cancelled", e)
        } ?: return response

        // Retry the original request with the fresh access token.
        response.close()
        val retryRequest = original.newBuilder()
            .header("Authorization", "Bearer $newAccessToken")
            .build()
        return chain.proceed(retryRequest)
    }
}
