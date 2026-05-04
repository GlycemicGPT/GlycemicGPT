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

    // --- refreshForInterceptor (called from TokenRefreshInterceptor on 401) ---

    @Test
    fun `refreshForInterceptor short-circuits when valid token is already stored`() = runTest {
        // Fast path: another caller already produced a valid access token.
        // refreshForInterceptor should return that token without hitting the
        // network. This is the bug-fix path for issue #520 -- when multiple
        // queued 401s arrive after an access token expired, only the first
        // one should refresh; every subsequent caller gets the freshly-stored
        // token here.
        every { authTokenStore.getToken() } returns "already-fresh-token"
        // Wire up a refresh client that throws on any call -- if the fast path
        // works, this client is never asked to do anything.
        every { refreshClientProvider.refreshClient } returns
            mockClientThrowing(IllegalStateException("Network call should not happen on fast path"))

        val manager = createManager()
        // originalToken=null is the load-bearing case: AuthInterceptor sends
        // the request with no Authorization header when the access token was
        // already expired client-side. The fast path should still trigger.
        val result = manager.refreshForInterceptor(null)

        assertEquals("already-fresh-token", result)
    }

    @Test
    fun `refreshForInterceptor refreshes when stored token equals originalToken`() = runTest {
        // Loop-guard: if the server 401s a fresh access token (e.g. revoked
        // session, IP change, server bug), the stored token equals the one
        // the request just used. Returning the stored token would loop the
        // request forever. We must actually refresh in that case.
        every { authTokenStore.getToken() } returns "rejected-token"
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { authTokenStore.getTokenExpiresAtMs() } returns System.currentTimeMillis() + 3_600_000

        val body = """
            {
                "access_token": "post-refresh-token",
                "refresh_token": "post-refresh-refresh",
                "token_type": "bearer",
                "expires_in": 3600,
                "user": {"id": "1", "email": "user@test.com", "role": "user"}
            }
        """.trimIndent()
        every { refreshClientProvider.refreshClient } returns mockClientReturning(fakeResponse(200, body))

        val manager = createManager()
        manager.onLoginSuccess(testScope)
        // The request that got 401 carried "rejected-token" and the store
        // still has "rejected-token" -- must refresh, not return the same
        // rejected value.
        val result = manager.refreshForInterceptor(originalToken = "rejected-token")

        assertEquals("post-refresh-token", result)
        verify { authTokenStore.saveCredentials(any(), "post-refresh-token", any(), any()) }
    }

    @Test
    fun `refreshForInterceptor performs refresh when no valid token stored`() = runTest {
        // Simulate AuthTokenStore's real behavior: getToken returns null until
        // saveCredentials persists a value, then returns the saved value. Without
        // this, the recursive proactive-refresh timer that fires on success would
        // re-enter performRefresh forever (state-based fast path requires a
        // non-null token).
        var savedAccess: String? = null
        every { authTokenStore.getToken() } answers { savedAccess }
        every { authTokenStore.saveCredentials(any(), any(), any(), any()) } answers {
            savedAccess = secondArg<String>()
        }
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { authTokenStore.getTokenExpiresAtMs() } returns System.currentTimeMillis() + 3_600_000

        val body = """
            {
                "access_token": "fresh-access",
                "refresh_token": "fresh-refresh",
                "token_type": "bearer",
                "expires_in": 3600,
                "user": {"id": "1", "email": "user@test.com", "role": "user"}
            }
        """.trimIndent()
        every { refreshClientProvider.refreshClient } returns mockClientReturning(fakeResponse(200, body))

        val manager = createManager()
        manager.onLoginSuccess(testScope) // sets retainedScope so success branch can reschedule
        val result = manager.refreshForInterceptor(null)

        assertEquals("fresh-access", result)
        assertEquals(AuthState.Authenticated, manager.authState.value)
        verify { authTokenStore.saveCredentials("https://test.example.com", "fresh-access", any(), "user@test.com") }
        verify { authTokenStore.saveRefreshToken("fresh-refresh") }
    }

    @Test
    fun `refreshForInterceptor returns null and sets Expired on 401 from server`() = runTest {
        every { authTokenStore.getToken() } returns null
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { refreshClientProvider.refreshClient } returns mockClientReturning(fakeResponse(401))

        val manager = createManager()
        val result = manager.refreshForInterceptor(null)

        assertEquals(null, result)
        assertTrue(manager.authState.value is AuthState.Expired)
        verify { authTokenStore.clearToken() }
    }

    @Test
    fun `refreshForInterceptor returns null on transient server error without changing state`() = runTest {
        // 5xx during interceptor refresh should NOT logout the user. The
        // caller's request will see the 401 and the app keeps trying.
        // (We avoid onLoginSuccess here because that schedules a proactive
        // refresh that would re-enter performRefresh under the test
        // scheduler's auto-advancing virtual time.)
        every { authTokenStore.getToken() } returns null
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { refreshClientProvider.refreshClient } returns mockClientReturning(fakeResponse(503))

        val manager = createManager()
        val result = manager.refreshForInterceptor(null)

        assertEquals(null, result)
        // Should not be Expired
        assertTrue(manager.authState.value !is AuthState.Expired)
        verify(exactly = 0) { authTokenStore.clearToken() }
    }

    /**
     * Regression for issue #520. The proactive refresh timer
     * ([performRefresh]) and the reactive interceptor refresh
     * ([refreshForInterceptor]) MUST share a single mutex so they cannot
     * both rotate the refresh token. Before this fix they had independent
     * locks and could each successfully rotate, leaving any in-flight
     * requests carrying a now-twice-stale refresh token, which the server's
     * replay detector then rejected.
     *
     * What this test asserts: under [UnconfinedTestDispatcher] both paths
     * complete with exactly ONE network call -- the second caller's
     * fast-path correctly observes the freshly-stored token from the first
     * caller and returns it without re-entering the refresh logic.
     *
     * What this test does NOT directly assert: lock contention behavior
     * under genuine concurrent execution. The fast-path / shared-state
     * behavior here is the load-bearing guarantee for the burst-of-401s
     * scenario. The mutex's actual contention semantics are a property of
     * [kotlinx.coroutines.sync.Mutex] itself.
     */
    @Test
    fun `proactive and interceptor refresh share a single mutex`() = runTest {
        // First call: getToken() returns null (must refresh).
        // After a successful refresh, getToken() should return the new token
        // so the second caller takes the fast path and does not hit the network.
        var refreshed = false
        every { authTokenStore.getToken() } answers {
            if (refreshed) "fresh-access" else null
        }
        every { authTokenStore.getRefreshToken() } returns "valid-refresh"
        every { authTokenStore.isRefreshTokenExpired() } returns false
        every { authTokenStore.getTokenExpiresAtMs() } returns System.currentTimeMillis() + 3_600_000

        val body = """
            {
                "access_token": "fresh-access",
                "refresh_token": "fresh-refresh",
                "token_type": "bearer",
                "expires_in": 3600,
                "user": {"id": "1", "email": "user@test.com", "role": "user"}
            }
        """.trimIndent()

        // Track network call count to prove the second caller skipped it.
        var networkCallCount = 0
        val client = mockk<OkHttpClient> {
            every { newCall(any()) } answers {
                mockk { every { execute() } answers {
                    networkCallCount++
                    // Flip `refreshed` so getToken() reports the new value the
                    // moment any subsequent caller checks. Subsequent callers
                    // run after this one releases the mutex (sequential
                    // execution under UnconfinedTestDispatcher), so they hit
                    // the fast path.
                    refreshed = true
                    fakeResponse(200, body)
                } }
            }
        }
        every { refreshClientProvider.refreshClient } returns client

        val manager = createManager()
        manager.onLoginSuccess(testScope)

        // Run both refresh paths sequentially under the test scheduler.
        // The mutex serializes them; the second caller hits the fast path.
        manager.performRefresh(testScope)
        val interceptorToken = manager.refreshForInterceptor(null)

        assertEquals("fresh-access", interceptorToken)
        // Critical assertion: only one network call happened total.
        assertEquals("expected one /refresh call across both paths, got $networkCallCount",
            1, networkCallCount)
    }
}
