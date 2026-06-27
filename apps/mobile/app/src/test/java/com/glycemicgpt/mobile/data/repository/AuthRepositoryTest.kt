package com.glycemicgpt.mobile.data.repository

import android.content.Context
import com.glycemicgpt.mobile.data.auth.AuthManager
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.local.AuthTokenStore
import com.glycemicgpt.mobile.data.local.GlucoseRangeStore
import com.glycemicgpt.mobile.data.local.AnalyticsSettingsStore
import com.glycemicgpt.mobile.data.local.PumpProfileStore
import com.glycemicgpt.mobile.data.local.SafetyLimitsStore
import com.glycemicgpt.mobile.data.remote.GlycemicGptApi
import com.glycemicgpt.mobile.data.remote.dto.GlucoseRangeResponse
import com.glycemicgpt.mobile.data.remote.dto.GlucoseUnitResponse
import com.glycemicgpt.mobile.data.remote.dto.HealthResponse
import com.glycemicgpt.mobile.data.remote.dto.LoginResponse
import com.glycemicgpt.mobile.data.remote.dto.MealIntelligenceResponse
import com.glycemicgpt.mobile.data.remote.dto.UserDto
import com.glycemicgpt.mobile.domain.model.GlucoseUnit
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.Response

@OptIn(ExperimentalCoroutinesApi::class)
class AuthRepositoryTest {

    private val appContext = mockk<Context>(relaxed = true)
    private val authTokenStore = mockk<AuthTokenStore>(relaxed = true) {
        every { getBaseUrl() } returns "https://test.example.com"
        every { isLoggedIn() } returns false
        every { getUserEmail() } returns null
    }
    private val glucoseRangeStore = mockk<GlucoseRangeStore>(relaxed = true)
    private val safetyLimitsStore = mockk<SafetyLimitsStore>(relaxed = true)
    private val analyticsSettingsStore = mockk<AnalyticsSettingsStore>(relaxed = true)
    private val pumpProfileStore = mockk<PumpProfileStore>(relaxed = true)
    private val appSettingsStore = mockk<AppSettingsStore>(relaxed = true)
    private val api = mockk<GlycemicGptApi>()
    private val deviceRepository = mockk<DeviceRepository>(relaxed = true)
    private val authManager = mockk<AuthManager>(relaxed = true)

    private val repository = AuthRepository(
        appContext, authTokenStore, glucoseRangeStore, safetyLimitsStore,
        analyticsSettingsStore, pumpProfileStore, appSettingsStore, api, deviceRepository, authManager,
    )

    private val testScope = TestScope(UnconfinedTestDispatcher())

    @Test
    fun `testConnection returns success on 200`() = runTest {
        coEvery { api.healthCheck() } returns Response.success(HealthResponse(status = "ok"))

        val result = repository.testConnection()

        assertTrue(result.isSuccess)
        assertEquals("Connected successfully", result.getOrNull())
    }

    @Test
    fun `testConnection returns failure on HTTP error`() = runTest {
        coEvery { api.healthCheck() } returns Response.error(500, "error".toResponseBody())

        val result = repository.testConnection()

        assertTrue(result.isFailure)
        assertTrue(result.exceptionOrNull()!!.message!!.contains("500"))
    }

    @Test
    fun `testConnection returns failure on network error`() = runTest {
        coEvery { api.healthCheck() } throws java.io.IOException("No route to host")

        val result = repository.testConnection()

        assertTrue(result.isFailure)
        assertEquals("No route to host", result.exceptionOrNull()!!.message)
    }

    @Test
    fun `login saves credentials on success`() = runTest {
        coEvery { api.login(any()) } returns Response.success(
            LoginResponse(
                accessToken = "jwt123",
                refreshToken = "refresh123",
                tokenType = "bearer",
                expiresIn = 3600,
                user = UserDto(id = "1", email = "user@test.com", role = "user"),
            ),
        )

        val result = repository.login("https://test.example.com", "user@test.com", "pass", testScope)

        assertTrue(result.success)
        assertEquals("user@test.com", result.email)
        assertNull(result.error)
        verify { authTokenStore.saveCredentials(any(), "jwt123", any(), "user@test.com") }
        verify { authTokenStore.saveRefreshToken("refresh123") }
    }

    @Test
    fun `login notifies AuthManager on success`() = runTest {
        coEvery { api.login(any()) } returns Response.success(
            LoginResponse(
                accessToken = "jwt123",
                refreshToken = "refresh123",
                tokenType = "bearer",
                expiresIn = 3600,
                user = UserDto(id = "1", email = "user@test.com", role = "user"),
            ),
        )

        repository.login("https://test.example.com", "user@test.com", "pass", testScope)

        verify { authManager.onLoginSuccess(any()) }
    }

    @Test
    fun `login registers device and fetches glucose range`() = runTest {
        coEvery { api.login(any()) } returns Response.success(
            LoginResponse(
                accessToken = "jwt123",
                refreshToken = "refresh123",
                tokenType = "bearer",
                expiresIn = 3600,
                user = UserDto(id = "1", email = "user@test.com", role = "user"),
            ),
        )
        coEvery { api.getGlucoseRange() } returns Response.success(
            GlucoseRangeResponse(urgentLow = 54f, lowTarget = 70f, highTarget = 180f, urgentHigh = 250f),
        )

        repository.login("https://test.example.com", "user@test.com", "pass", testScope)

        coVerify { deviceRepository.registerDevice() }
        coVerify { api.getGlucoseRange() }
    }

    @Test
    fun `login returns error on 401`() = runTest {
        coEvery { api.login(any()) } returns Response.error(401, "unauthorized".toResponseBody())

        val result = repository.login("https://test.example.com", "user@test.com", "wrong", testScope)

        assertFalse(result.success)
        assertEquals("Invalid email or password", result.error)
    }

    @Test
    fun `login returns error on empty response body`() = runTest {
        coEvery { api.login(any()) } returns Response.success(null)

        val result = repository.login("https://test.example.com", "user@test.com", "pass", testScope)

        assertFalse(result.success)
        assertEquals("Login failed: empty response from server", result.error)
    }

    @Test
    fun `login returns error on network failure`() = runTest {
        coEvery { api.login(any()) } throws java.io.IOException("timeout")

        val result = repository.login("https://test.example.com", "user@test.com", "pass", testScope)

        assertFalse(result.success)
        assertTrue(result.error!!.contains("timeout"))
    }

    @Test
    fun `login requires URL`() = runTest {
        val result = repository.login("", "user@test.com", "pass", testScope)

        assertFalse(result.success)
        assertEquals("Configure server URL first", result.error)
    }

    @Test
    fun `login requires email and password`() = runTest {
        val result1 = repository.login("https://test.example.com", "", "pass", testScope)
        assertFalse(result1.success)
        assertEquals("Email and password are required", result1.error)

        val result2 = repository.login("https://test.example.com", "user@test.com", "", testScope)
        assertFalse(result2.success)
        assertEquals("Email and password are required", result2.error)
    }

    @Test
    fun `logout clears tokens and notifies AuthManager`() {
        repository.logout(testScope)

        verify { authTokenStore.clearToken() }
        verify { safetyLimitsStore.clear() }
        verify { analyticsSettingsStore.clear() }
        verify { pumpProfileStore.clear() }
        verify { appSettingsStore.glucoseUnit = GlucoseUnit.MGDL }
        // Meal intelligence is per-account; logout resets it to the default (ON)
        // so a stale value can't carry into the next account before its reconcile.
        verify { appSettingsStore.mealIntelligenceEnabled = true }
        verify { authManager.onLogout() }
    }

    @Test
    fun `logout unregisters device`() {
        repository.logout(testScope)

        coVerify { deviceRepository.unregisterDevice() }
    }

    @Test
    fun `isValidUrl accepts HTTPS`() {
        assertTrue(repository.isValidUrl("https://example.com"))
    }

    @Test
    fun `isValidUrl rejects malformed URL`() {
        assertFalse(repository.isValidUrl("not-a-url"))
    }

    @Test
    fun `updateGlucoseUnit PATCHes the account and caches the server value`() = runTest {
        coEvery { api.patchGlucoseUnit(any()) } returns Response.success(
            GlucoseUnitResponse(glucoseUnit = "mmol"),
        )

        val result = repository.updateGlucoseUnit(GlucoseUnit.MMOL)

        assertTrue(result.isSuccess)
        assertEquals(GlucoseUnit.MMOL, result.getOrNull())
        coVerify { api.patchGlucoseUnit(match { it.glucoseUnit == "mmol" }) }
        verify { appSettingsStore.glucoseUnit = GlucoseUnit.MMOL }
    }

    @Test
    fun `updateGlucoseUnit returns failure and leaves cache untouched on HTTP error`() = runTest {
        coEvery { api.patchGlucoseUnit(any()) } returns Response.error(500, "boom".toResponseBody())

        val result = repository.updateGlucoseUnit(GlucoseUnit.MMOL)

        assertTrue(result.isFailure)
        verify(exactly = 0) { appSettingsStore.glucoseUnit = any() }
    }

    @Test
    fun `refreshGlucoseUnit writes the backend value into the cache`() = runTest {
        coEvery { api.getGlucoseUnit() } returns Response.success(
            GlucoseUnitResponse(glucoseUnit = "mmol"),
        )

        repository.refreshGlucoseUnit()

        verify { appSettingsStore.glucoseUnit = GlucoseUnit.MMOL }
    }

    @Test
    fun `refreshGlucoseUnit leaves cache untouched when the backend call fails`() = runTest {
        coEvery { api.getGlucoseUnit() } throws java.io.IOException("offline")

        repository.refreshGlucoseUnit()

        verify(exactly = 0) { appSettingsStore.glucoseUnit = any() }
    }

    @Test
    fun `updateMealIntelligence PATCHes the account and caches the server value`() = runTest {
        coEvery { api.patchMealIntelligence(any()) } returns Response.success(
            MealIntelligenceResponse(enabled = false),
        )

        val result = repository.updateMealIntelligence(false)

        assertTrue(result.isSuccess)
        assertEquals(false, result.getOrNull())
        coVerify { api.patchMealIntelligence(match { !it.enabled }) }
        verify { appSettingsStore.mealIntelligenceEnabled = false }
    }

    @Test
    fun `updateMealIntelligence returns failure and leaves cache untouched on HTTP error`() =
        runTest {
            coEvery { api.patchMealIntelligence(any()) } returns
                Response.error(500, "boom".toResponseBody())

            val result = repository.updateMealIntelligence(false)

            assertTrue(result.isFailure)
            verify(exactly = 0) { appSettingsStore.mealIntelligenceEnabled = any() }
        }

    @Test
    fun `refreshMealIntelligence writes the backend value into the cache`() = runTest {
        coEvery { api.getMealIntelligence() } returns Response.success(
            MealIntelligenceResponse(enabled = false),
        )

        repository.refreshMealIntelligence()

        verify { appSettingsStore.mealIntelligenceEnabled = false }
    }

    @Test
    fun `refreshMealIntelligence leaves cache untouched when the backend call fails`() = runTest {
        coEvery { api.getMealIntelligence() } throws java.io.IOException("offline")

        repository.refreshMealIntelligence()

        verify(exactly = 0) { appSettingsStore.mealIntelligenceEnabled = any() }
    }

    @Test
    fun `refreshMealIntelligence fails closed on a 403 (forbidden account)`() = runTest {
        coEvery { api.getMealIntelligence() } returns
            Response.error(403, "forbidden".toResponseBody())

        repository.refreshMealIntelligence()

        verify { appSettingsStore.mealIntelligenceEnabled = false }
    }

    @Test
    fun `updateMealIntelligence fails closed on a 401`() = runTest {
        coEvery { api.patchMealIntelligence(any()) } returns
            Response.error(401, "unauthorized".toResponseBody())

        val result = repository.updateMealIntelligence(true)

        assertTrue(result.isFailure)
        verify { appSettingsStore.mealIntelligenceEnabled = false }
    }

    @Test
    fun `refreshGlucoseUnit flags seed-pending for a seed-owned mmol preference`() = runTest {
        coEvery { api.getGlucoseUnit() } returns Response.success(
            GlucoseUnitResponse(glucoseUnit = "mmol", glucoseUnitSource = "seed"),
        )

        repository.refreshGlucoseUnit()

        verify { appSettingsStore.glucoseUnit = GlucoseUnit.MMOL }
        verify { appSettingsStore.glucoseUnitSeedPending = true }
    }

    @Test
    fun `refreshGlucoseUnit does not flag seed-pending for a seed-owned mgdl preference`() =
        runTest {
            coEvery { api.getGlucoseUnit() } returns Response.success(
                GlucoseUnitResponse(glucoseUnit = "mgdl", glucoseUnitSource = "seed"),
            )

            repository.refreshGlucoseUnit()

            verify { appSettingsStore.glucoseUnit = GlucoseUnit.MGDL }
            verify { appSettingsStore.glucoseUnitSeedPending = false }
        }

    @Test
    fun `refreshGlucoseUnit does not flag seed-pending once the user has chosen`() = runTest {
        coEvery { api.getGlucoseUnit() } returns Response.success(
            GlucoseUnitResponse(glucoseUnit = "mmol", glucoseUnitSource = "user"),
        )

        repository.refreshGlucoseUnit()

        verify { appSettingsStore.glucoseUnit = GlucoseUnit.MMOL }
        verify { appSettingsStore.glucoseUnitSeedPending = false }
    }

    @Test
    fun `updateGlucoseUnit clears seed-pending on success`() = runTest {
        coEvery { api.patchGlucoseUnit(any()) } returns Response.success(
            GlucoseUnitResponse(glucoseUnit = "mmol", glucoseUnitSource = "user"),
        )

        repository.updateGlucoseUnit(GlucoseUnit.MMOL)

        verify { appSettingsStore.glucoseUnitSeedPending = false }
    }

    @Test
    fun `acknowledgeGlucoseUnitSeed clears seed-pending and succeeds`() = runTest {
        coEvery { api.acknowledgeGlucoseUnitSeed() } returns Response.success(
            GlucoseUnitResponse(glucoseUnit = "mmol", glucoseUnitSource = "user"),
        )

        val result = repository.acknowledgeGlucoseUnitSeed()

        assertTrue(result.isSuccess)
        coVerify { api.acknowledgeGlucoseUnitSeed() }
        verify { appSettingsStore.glucoseUnitSeedPending = false }
    }

    @Test
    fun `acknowledgeGlucoseUnitSeed returns failure and leaves cache untouched on HTTP error`() =
        runTest {
            coEvery { api.acknowledgeGlucoseUnitSeed() } returns
                Response.error(500, "boom".toResponseBody())

            val result = repository.acknowledgeGlucoseUnitSeed()

            assertTrue(result.isFailure)
            verify(exactly = 0) { appSettingsStore.glucoseUnitSeedPending = any() }
        }
}
