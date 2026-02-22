package com.glycemicgpt.mobile.data.remote

import com.glycemicgpt.mobile.data.auth.AuthManager
import com.glycemicgpt.mobile.data.auth.RefreshClientProvider
import com.glycemicgpt.mobile.data.local.AuthTokenStore
import com.squareup.moshi.Moshi
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import okhttp3.Call
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.IOException
import javax.inject.Provider

class TokenRefreshInterceptorTest {

    private val authTokenStore = mockk<AuthTokenStore>(relaxed = true)
    private val refreshClientProvider = mockk<RefreshClientProvider>(relaxed = true)
    private val moshi = Moshi.Builder().build()
    private val authManager = mockk<AuthManager>(relaxed = true)
    private val authManagerProvider = Provider { authManager }

    private fun createInterceptor() =
        TokenRefreshInterceptor(authTokenStore, refreshClientProvider, moshi, authManagerProvider)

    private fun buildResponse(code: Int, request: Request): Response =
        Response.Builder()
            .protocol(Protocol.HTTP_1_1)
            .code(code)
            .message(if (code == 200) "OK" else "Unauthorized")
            .request(request)
            .body("".toResponseBody())
            .build()

    private fun mockRefreshClient(responseCode: Int): OkHttpClient {
        val refreshRequest = Request.Builder().url("http://localhost/api/auth/mobile/refresh").build()
        val refreshResponse = buildResponse(responseCode, refreshRequest)
        val call = mockk<Call> { every { execute() } returns refreshResponse }
        return mockk { every { newCall(any()) } returns call }
    }

    private fun mockRefreshClientThrowing(exception: Exception): OkHttpClient {
        val call = mockk<Call> { every { execute() } throws exception }
        return mockk { every { newCall(any()) } returns call }
    }

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
        // Should NOT attempt refresh for the refresh endpoint itself
        verify(exactly = 0) { authTokenStore.clearToken() }
    }

    @Test
    fun `401 with expired refresh token notifies AuthManager`() {
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
    }

    @Test
    fun `401 retries with refreshed token when another thread already refreshed`() {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        // Simulate another thread already refreshed
        every { authTokenStore.getRawToken() } returns "new-token-from-other-thread"

        val interceptor = createInterceptor()
        val request = Request.Builder()
            .url("http://localhost/api/test")
            .header("Authorization", "Bearer old-token")
            .build()

        val retryResponse = buildResponse(200, request)
        val chain = mockk<Interceptor.Chain> {
            every { request() } returns request
            every { proceed(any()) } returnsMany listOf(buildResponse(401, request), retryResponse)
        }

        val response = interceptor.intercept(chain)
        assertEquals(200, response.code)
    }

    @Test
    fun `refresh 401 clears tokens and notifies AuthManager`() {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { authTokenStore.getRawToken() } returns null
        every { authTokenStore.getBaseUrl() } returns "https://test.example.com"
        every { refreshClientProvider.refreshClient } returns mockRefreshClient(401)

        val interceptor = createInterceptor()
        val request = Request.Builder()
            .url("http://localhost/api/test")
            .header("Authorization", "Bearer expired-token")
            .build()
        val chain = mockk<Interceptor.Chain> {
            every { request() } returns request
            every { proceed(any()) } returns buildResponse(401, request)
        }

        interceptor.intercept(chain)
        verify { authTokenStore.clearToken() }
        verify { authManager.onRefreshFailed() }
    }

    @Test
    fun `refresh 403 clears tokens and notifies AuthManager`() {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { authTokenStore.getRawToken() } returns null
        every { authTokenStore.getBaseUrl() } returns "https://test.example.com"
        every { refreshClientProvider.refreshClient } returns mockRefreshClient(403)

        val interceptor = createInterceptor()
        val request = Request.Builder()
            .url("http://localhost/api/test")
            .header("Authorization", "Bearer expired-token")
            .build()
        val chain = mockk<Interceptor.Chain> {
            every { request() } returns request
            every { proceed(any()) } returns buildResponse(401, request)
        }

        interceptor.intercept(chain)
        verify { authTokenStore.clearToken() }
        verify { authManager.onRefreshFailed() }
    }

    @Test
    fun `refresh 500 preserves tokens for retry`() {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { authTokenStore.getRawToken() } returns null
        every { authTokenStore.getBaseUrl() } returns "https://test.example.com"
        every { refreshClientProvider.refreshClient } returns mockRefreshClient(500)

        val interceptor = createInterceptor()
        val request = Request.Builder()
            .url("http://localhost/api/test")
            .header("Authorization", "Bearer expired-token")
            .build()
        val chain = mockk<Interceptor.Chain> {
            every { request() } returns request
            every { proceed(any()) } returns buildResponse(401, request)
        }

        interceptor.intercept(chain)
        verify(exactly = 0) { authTokenStore.clearToken() }
        verify(exactly = 0) { authManager.onRefreshFailed() }
    }

    @Test
    fun `refresh 502 gateway error preserves tokens for retry`() {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { authTokenStore.getRawToken() } returns null
        every { authTokenStore.getBaseUrl() } returns "https://test.example.com"
        every { refreshClientProvider.refreshClient } returns mockRefreshClient(502)

        val interceptor = createInterceptor()
        val request = Request.Builder()
            .url("http://localhost/api/test")
            .header("Authorization", "Bearer expired-token")
            .build()
        val chain = mockk<Interceptor.Chain> {
            every { request() } returns request
            every { proceed(any()) } returns buildResponse(401, request)
        }

        interceptor.intercept(chain)
        verify(exactly = 0) { authTokenStore.clearToken() }
        verify(exactly = 0) { authManager.onRefreshFailed() }
    }

    @Test
    fun `refresh 503 service unavailable preserves tokens for retry`() {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { authTokenStore.getRawToken() } returns null
        every { authTokenStore.getBaseUrl() } returns "https://test.example.com"
        every { refreshClientProvider.refreshClient } returns mockRefreshClient(503)

        val interceptor = createInterceptor()
        val request = Request.Builder()
            .url("http://localhost/api/test")
            .header("Authorization", "Bearer expired-token")
            .build()
        val chain = mockk<Interceptor.Chain> {
            every { request() } returns request
            every { proceed(any()) } returns buildResponse(401, request)
        }

        interceptor.intercept(chain)
        verify(exactly = 0) { authTokenStore.clearToken() }
        verify(exactly = 0) { authManager.onRefreshFailed() }
    }

    @Test
    fun `refresh network error preserves tokens for retry`() {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { authTokenStore.getRawToken() } returns null
        every { authTokenStore.getBaseUrl() } returns "https://test.example.com"
        every { refreshClientProvider.refreshClient } returns mockRefreshClientThrowing(IOException("Network unreachable"))

        val interceptor = createInterceptor()
        val request = Request.Builder()
            .url("http://localhost/api/test")
            .header("Authorization", "Bearer expired-token")
            .build()
        val chain = mockk<Interceptor.Chain> {
            every { request() } returns request
            every { proceed(any()) } returns buildResponse(401, request)
        }

        interceptor.intercept(chain)
        verify(exactly = 0) { authTokenStore.clearToken() }
        verify(exactly = 0) { authManager.onRefreshFailed() }
    }
}
