package com.glycemicgpt.mobile.data.auth

import com.glycemicgpt.mobile.data.local.AuthTokenStore
import com.squareup.moshi.Moshi
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import okhttp3.Call
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.IOException

@OptIn(ExperimentalCoroutinesApi::class)
class AuthManagerTest {

    private val authTokenStore = mockk<AuthTokenStore>(relaxed = true)
    private val moshi = Moshi.Builder().build()
    private lateinit var refreshClientProvider: RefreshClientProvider

    private val testDispatcher = UnconfinedTestDispatcher()
    private lateinit var testScope: TestScope

    /** Builds a fake OkHttp [Response] with the given code and JSON body. */
    private fun fakeResponse(code: Int, body: String = ""): Response {
        val request = Request.Builder().url("http://localhost/api/auth/mobile/refresh").build()
        return Response.Builder()
            .request(request)
            .protocol(Protocol.HTTP_1_1)
            .code(code)
            .message(if (code == 200) "OK" else "Error")
            .body(body.toResponseBody("application/json".toMediaType()))
            .build()
    }

    /** Creates a mock OkHttpClient that returns the given response on any call. */
    private fun mockClientReturning(response: Response): OkHttpClient {
        val call = mockk<Call> { every { execute() } returns response }
        return mockk { every { newCall(any()) } returns call }
    }

    /** Creates a mock OkHttpClient that throws on any call. */
    private fun mockClientThrowing(exception: Exception): OkHttpClient {
        val call = mockk<Call> { every { execute() } throws exception }
        return mockk { every { newCall(any()) } returns call }
    }

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
        testScope = TestScope(testDispatcher)

        // Default: base URL is configured
        every { authTokenStore.getBaseUrl() } returns "https://test.example.com"

        // Default: mock client returns 200 (overridden per test as needed)
        refreshClientProvider = mockk()
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun createManager() = AuthManager(authTokenStore, refreshClientProvider, moshi).also {
        it.ioDispatcher = testDispatcher
    }

    // --- validateOnStartup ---

    @Test
    fun `validateOnStartup sets Unauthenticated when no refresh token`() {
        every { authTokenStore.getRefreshToken() } returns null

        val manager = createManager()
        manager.validateOnStartup(testScope)

        assertEquals(AuthState.Unauthenticated, manager.authState.value)
    }

    @Test
    fun `validateOnStartup sets Expired when refresh token is expired`() {
        every { authTokenStore.getRefreshToken() } returns "expired-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns true

        val manager = createManager()
        manager.validateOnStartup(testScope)

        assertTrue(manager.authState.value is AuthState.Expired)
    }

    @Test
    fun `validateOnStartup sets Authenticated when access token is valid`() {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { authTokenStore.getToken() } returns "valid-access-token"
        every { authTokenStore.getTokenExpiresAtMs() } returns System.currentTimeMillis() + 3_600_000

        val manager = createManager()
        manager.validateOnStartup(testScope)

        assertEquals(AuthState.Authenticated, manager.authState.value)
    }

    @Test
    fun `validateOnStartup sets Expired after retries exhausted on 500 with no token`() {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { authTokenStore.getToken() } returns null // Access token expired
        every { authTokenStore.getRawToken() } returns null // No raw token either
        every { refreshClientProvider.refreshClient } returns mockClientReturning(fakeResponse(500))

        val manager = createManager()
        manager.validateOnStartup(testScope)
        testScope.testScheduler.advanceUntilIdle()

        // After 3 attempts (0..2), should give up and set Expired
        assertTrue(manager.authState.value is AuthState.Expired)
    }

    // --- performRefresh (also covers the validateOnStartup->performRefresh delegation path) ---

    @Test
    fun `performRefresh succeeds and saves new tokens`() = runTest {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { authTokenStore.getTokenExpiresAtMs() } returns System.currentTimeMillis() + 3_600_000

        val body = """
            {
                "access_token": "refreshed-access",
                "refresh_token": "refreshed-refresh",
                "token_type": "bearer",
                "expires_in": 3600,
                "user": {"id": "1", "email": "user@test.com", "role": "user"}
            }
        """.trimIndent()
        every { refreshClientProvider.refreshClient } returns mockClientReturning(fakeResponse(200, body))

        val manager = createManager()
        manager.performRefresh(testScope)

        assertEquals(AuthState.Authenticated, manager.authState.value)
        verify { authTokenStore.saveCredentials("https://test.example.com", "refreshed-access", any(), "user@test.com") }
        verify { authTokenStore.saveRefreshToken("refreshed-refresh") }
    }

    @Test
    fun `performRefresh sets Unauthenticated when no refresh token`() = runTest {
        every { authTokenStore.getRefreshToken() } returns null

        val manager = createManager()
        manager.performRefresh(testScope)

        assertEquals(AuthState.Unauthenticated, manager.authState.value)
    }

    @Test
    fun `performRefresh sets Expired when refresh token is expired`() = runTest {
        every { authTokenStore.getRefreshToken() } returns "expired-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns true

        val manager = createManager()
        manager.performRefresh(testScope)

        assertTrue(manager.authState.value is AuthState.Expired)
    }

    @Test
    fun `performRefresh sets Expired when no base URL configured`() = runTest {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { authTokenStore.getBaseUrl() } returns null

        val manager = createManager()
        manager.performRefresh(testScope)

        assertTrue(manager.authState.value is AuthState.Expired)
    }

    @Test
    fun `performRefresh sets Expired on 401 HTTP error`() = runTest {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { refreshClientProvider.refreshClient } returns mockClientReturning(fakeResponse(401))

        val manager = createManager()
        manager.performRefresh(testScope)

        assertTrue(manager.authState.value is AuthState.Expired)
        verify { authTokenStore.clearToken() }
    }

    @Test
    fun `performRefresh sets Expired on 403 HTTP error`() = runTest {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { refreshClientProvider.refreshClient } returns mockClientReturning(fakeResponse(403))

        val manager = createManager()
        manager.performRefresh(testScope)

        assertTrue(manager.authState.value is AuthState.Expired)
        verify { authTokenStore.clearToken() }
    }

    @Test
    fun `performRefresh preserves session on 500 with existing raw token`() = runTest {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { authTokenStore.getRawToken() } returns "existing-token"
        every { authTokenStore.getTokenExpiresAtMs() } returns System.currentTimeMillis() + 3_600_000
        every { refreshClientProvider.refreshClient } returns mockClientReturning(fakeResponse(500))

        val manager = createManager()
        manager.performRefresh(testScope)

        // Should stay authenticated and schedule retry, NOT set Expired
        assertEquals(AuthState.Authenticated, manager.authState.value)
        verify(exactly = 0) { authTokenStore.clearToken() }
    }

    @Test
    fun `performRefresh stays Refreshing on 500 without raw token`() = runTest {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { authTokenStore.getRawToken() } returns null
        every { refreshClientProvider.refreshClient } returns mockClientReturning(fakeResponse(500))

        val manager = createManager()
        manager.performRefresh(testScope)

        // No access token available -- should stay in Refreshing for retry
        assertEquals(AuthState.Refreshing, manager.authState.value)
        verify(exactly = 0) { authTokenStore.clearToken() }
    }

    @Test
    fun `performRefresh preserves session on 502 gateway error`() = runTest {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { authTokenStore.getRawToken() } returns "existing-token"
        every { authTokenStore.getTokenExpiresAtMs() } returns System.currentTimeMillis() + 3_600_000
        every { refreshClientProvider.refreshClient } returns mockClientReturning(fakeResponse(502))

        val manager = createManager()
        manager.performRefresh(testScope)

        assertEquals(AuthState.Authenticated, manager.authState.value)
        verify(exactly = 0) { authTokenStore.clearToken() }
    }

    @Test
    fun `performRefresh preserves session on 503 service unavailable`() = runTest {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { authTokenStore.getRawToken() } returns "existing-token"
        every { authTokenStore.getTokenExpiresAtMs() } returns System.currentTimeMillis() + 3_600_000
        every { refreshClientProvider.refreshClient } returns mockClientReturning(fakeResponse(503))

        val manager = createManager()
        manager.performRefresh(testScope)

        assertEquals(AuthState.Authenticated, manager.authState.value)
        verify(exactly = 0) { authTokenStore.clearToken() }
    }

    @Test
    fun `performRefresh stays Authenticated on network error if raw token exists`() = runTest {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { authTokenStore.getRawToken() } returns "existing-token"
        every { authTokenStore.getTokenExpiresAtMs() } returns System.currentTimeMillis() + 3_600_000
        every { refreshClientProvider.refreshClient } returns mockClientThrowing(IOException("Network unreachable"))

        val manager = createManager()
        manager.performRefresh(testScope)

        assertEquals(AuthState.Authenticated, manager.authState.value)
    }

    @Test
    fun `performRefresh sets Expired on network error if no raw token`() = runTest {
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { authTokenStore.getRawToken() } returns null
        every { refreshClientProvider.refreshClient } returns mockClientThrowing(IOException("Network unreachable"))

        val manager = createManager()
        manager.performRefresh(testScope)

        assertTrue(manager.authState.value is AuthState.Expired)
    }

    // --- onLoginSuccess / onLogout ---

    @Test
    fun `onLoginSuccess sets Authenticated`() {
        every { authTokenStore.getTokenExpiresAtMs() } returns System.currentTimeMillis() + 3_600_000

        val manager = createManager()
        manager.onLoginSuccess(testScope)

        assertEquals(AuthState.Authenticated, manager.authState.value)
    }

    @Test
    fun `onLogout sets Unauthenticated`() {
        val manager = createManager()
        manager.onLoginSuccess(testScope)
        manager.onLogout()

        assertEquals(AuthState.Unauthenticated, manager.authState.value)
    }

    @Test
    fun `onRefreshFailed sets Expired`() {
        val manager = createManager()
        manager.onRefreshFailed()

        assertTrue(manager.authState.value is AuthState.Expired)
    }

    @Test
    fun `onInterceptorRefreshSuccess sets Authenticated`() {
        val manager = createManager()
        every { authTokenStore.getTokenExpiresAtMs() } returns System.currentTimeMillis() + 3_600_000

        manager.onInterceptorRefreshSuccess(testScope)

        assertEquals(AuthState.Authenticated, manager.authState.value)
    }
}
