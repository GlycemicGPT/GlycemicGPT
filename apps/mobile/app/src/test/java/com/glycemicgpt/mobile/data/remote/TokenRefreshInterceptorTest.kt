package com.glycemicgpt.mobile.data.remote

import com.glycemicgpt.mobile.data.auth.AuthManager
import com.glycemicgpt.mobile.data.local.AuthTokenStore
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import okhttp3.Interceptor
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import javax.inject.Provider

class TokenRefreshInterceptorTest {

    private val authTokenStore = mockk<AuthTokenStore>(relaxed = true)
    // Relax only Unit-returning side effects so void calls like onRefreshFailed
    // don't require explicit stubbing, but suspend functions must be stubbed
    // explicitly. Full relaxed-mockk on AuthManager can produce expensive
    // default-coroutine machinery in some configurations.
    private val authManager = mockk<AuthManager>(relaxUnitFun = true)
    private val authManagerProvider = Provider { authManager }

    private fun createInterceptor() =
        TokenRefreshInterceptor(authTokenStore, authManagerProvider)

    private fun buildResponse(code: Int, request: Request): Response =
        Response.Builder()
            .protocol(Protocol.HTTP_1_1)
            .code(code)
            .message(if (code == 200) "OK" else "Unauthorized")
            .request(request)
            .body("".toResponseBody())
            .build()

    // --- pass-through cases (no refresh attempted) ---

    @Test
    fun `non-401 responses pass through unchanged`() {
        val interceptor = createInterceptor()
        val request = Request.Builder().url("http://localhost/api/test").build()
        val chain = mockk<Interceptor.Chain> {
            every { request() } returns request
            every { proceed(any()) } returns buildResponse(200, request)
        }

        val response = interceptor.intercept(chain)

        assertEquals(200, response.code)
        coVerify(exactly = 0) { authManager.refreshForInterceptor(any()) }
    }

    @Test
    fun `401 without refresh token passes through`() {
        every { authTokenStore.getRefreshToken() } returns null

        val interceptor = createInterceptor()
        val request = Request.Builder()
            .url("http://localhost/api/test")
            .header("Authorization", "Bearer expired-token")
            .build()
        val chain = mockk<Interceptor.Chain> {
            every { request() } returns request
            every { proceed(any()) } returns buildResponse(401, request)
        }

        val response = interceptor.intercept(chain)

        assertEquals(401, response.code)
        coVerify(exactly = 0) { authManager.refreshForInterceptor(any()) }
    }

    @Test
    fun `401 on refresh endpoint itself does not retry`() {
        every { authTokenStore.getRefreshToken() } returns "some-refresh-token"

        val interceptor = createInterceptor()
        val request = Request.Builder()
            .url("http://localhost/api/auth/mobile/refresh")
            .build()
        val chain = mockk<Interceptor.Chain> {
            every { request() } returns request
            every { proceed(any()) } returns buildResponse(401, request)
        }

        val response = interceptor.intercept(chain)

        assertEquals(401, response.code)
        coVerify(exactly = 0) { authManager.refreshForInterceptor(any()) }
        verify(exactly = 0) { authTokenStore.clearToken() }
    }

    @Test
    fun `401 with expired refresh token notifies AuthManager and clears tokens`() {
        every { authTokenStore.getRefreshToken() } returns "expired-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns true

        val interceptor = createInterceptor()
        val request = Request.Builder()
            .url("http://localhost/api/test")
            .header("Authorization", "Bearer expired-token")
            .build()
        val chain = mockk<Interceptor.Chain> {
            every { request() } returns request
            every { proceed(any()) } returns buildResponse(401, request)
        }

        val response = interceptor.intercept(chain)

        assertEquals(401, response.code)
        verify { authTokenStore.clearToken() }
        verify { authManager.onRefreshFailed() }
        coVerify(exactly = 0) { authManager.refreshForInterceptor(any()) }
    }

    // --- delegation to AuthManager.refreshForInterceptor ---

    @Test
    fun `401 retries with token returned by AuthManager`() {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        coEvery { authManager.refreshForInterceptor(any()) } returns "new-access-token"

        val interceptor = createInterceptor()
        val request = Request.Builder()
            .url("http://localhost/api/test")
            .header("Authorization", "Bearer expired-token")
            .build()

        val retryResponse = buildResponse(200, request)
        val chain = mockk<Interceptor.Chain> {
            every { request() } returns request
            every { proceed(any()) } returnsMany listOf(buildResponse(401, request), retryResponse)
        }

        val response = interceptor.intercept(chain)

        assertEquals(200, response.code)
        coVerify(exactly = 1) { authManager.refreshForInterceptor(any()) }
        // Verify the retry request carried the new bearer
        verify {
            chain.proceed(match { req ->
                req.header("Authorization") == "Bearer new-access-token"
            })
        }
    }

    /**
     * Regression for issue #520. AuthInterceptor omits the Authorization
     * header entirely when the access token has already expired
     * ([AuthTokenStore.getToken] returns null for expired tokens). The 401
     * we get back therefore has no original token to compare against. The
     * old implementation's double-check did `currentToken != null &&
     * originalToken != null && currentToken != originalToken` -- which is
     * always false when originalToken is null, so every queued 401 fell
     * through to a fresh refresh and replayed the previous refresh token.
     *
     * The fix routes through AuthManager.refreshForInterceptor, whose
     * fast-path uses `getToken()` to detect a freshly-stored token without
     * any comparison against the original request.
     */
    @Test
    fun `401 with null Authorization header still retries via AuthManager`() {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        coEvery { authManager.refreshForInterceptor(any()) } returns "fresh-access-token"

        val interceptor = createInterceptor()
        // No Authorization header on the original request -- this is the
        // exact shape the bug produced.
        val request = Request.Builder()
            .url("http://localhost/api/test")
            .build()
        assertTrue("test setup: request should have no Authorization header",
            request.header("Authorization") == null)

        val retryResponse = buildResponse(200, request)
        val chain = mockk<Interceptor.Chain> {
            every { request() } returns request
            every { proceed(any()) } returnsMany listOf(buildResponse(401, request), retryResponse)
        }

        val response = interceptor.intercept(chain)

        assertEquals(200, response.code)
        coVerify(exactly = 1) { authManager.refreshForInterceptor(any()) }
        verify {
            chain.proceed(match { req ->
                req.header("Authorization") == "Bearer fresh-access-token"
            })
        }
    }

    @Test
    fun `401 returns original response when AuthManager returns null`() {
        // refreshForInterceptor returns null on transient failures (5xx/network)
        // and on expired refresh tokens. Either way, we hand the 401 back to
        // the caller and let app-level logic handle session state.
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        coEvery { authManager.refreshForInterceptor(any()) } returns null

        val interceptor = createInterceptor()
        val request = Request.Builder()
            .url("http://localhost/api/test")
            .header("Authorization", "Bearer expired-token")
            .build()
        val chain = mockk<Interceptor.Chain> {
            every { request() } returns request
            every { proceed(any()) } returns buildResponse(401, request)
        }

        val response = interceptor.intercept(chain)

        assertEquals(401, response.code)
        coVerify(exactly = 1) { authManager.refreshForInterceptor(any()) }
    }
}
