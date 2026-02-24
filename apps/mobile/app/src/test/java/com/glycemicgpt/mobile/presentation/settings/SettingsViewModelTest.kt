package com.glycemicgpt.mobile.presentation.settings

import android.content.Context
import android.os.PowerManager
import com.glycemicgpt.mobile.data.auth.AuthManager
import com.glycemicgpt.mobile.data.auth.AuthState
import com.glycemicgpt.mobile.data.local.AlertSoundStore
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.local.GlucoseRangeStore
import com.glycemicgpt.mobile.data.local.PumpCredentialStore
import com.glycemicgpt.mobile.data.local.SafetyLimitsStore
import com.glycemicgpt.mobile.service.AlertNotificationManager
import com.glycemicgpt.mobile.data.repository.AuthRepository
import com.glycemicgpt.mobile.data.repository.LoginResult
import com.glycemicgpt.mobile.data.update.AppUpdateChecker
import com.glycemicgpt.mobile.data.update.DownloadResult
import com.glycemicgpt.mobile.data.update.UpdateCheckResult
import com.glycemicgpt.mobile.data.update.UpdateInfo
import com.glycemicgpt.mobile.domain.plugin.DevicePlugin
import com.glycemicgpt.mobile.domain.plugin.Plugin
import com.glycemicgpt.mobile.domain.plugin.PluginMetadata
import com.glycemicgpt.mobile.plugin.PluginRegistry
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

@OptIn(ExperimentalCoroutinesApi::class)
class SettingsViewModelTest {

    private val testDispatcher = UnconfinedTestDispatcher()
    private val pumpCredentialStore = mockk<PumpCredentialStore>(relaxed = true) {
        every { isPaired() } returns false
        every { getPairedAddress() } returns null
    }
    private val appSettingsStore = mockk<AppSettingsStore>(relaxed = true) {
        every { backendSyncEnabled } returns true
        every { dataRetentionDays } returns 7
    }
    private val powerManager = mockk<PowerManager>(relaxed = true) {
        every { isIgnoringBatteryOptimizations(any()) } returns false
    }
    private val appContext = mockk<Context>(relaxed = true) {
        every { getSystemService(Context.POWER_SERVICE) } returns powerManager
    }
    private val authRepository = mockk<AuthRepository>(relaxed = true) {
        every { getBaseUrl() } returns "https://test.example.com"
        every { isLoggedIn() } returns false
        every { getUserEmail() } returns null
    }
    private val glucoseRangeStore = mockk<GlucoseRangeStore>(relaxed = true) {
        every { isStale(any()) } returns false
    }
    private val safetyLimitsStore = mockk<SafetyLimitsStore>(relaxed = true) {
        every { isStale(any()) } returns false
    }
    private val appUpdateChecker = mockk<AppUpdateChecker>()
    private val authManager = mockk<AuthManager>(relaxed = true) {
        every { authState } returns MutableStateFlow(AuthState.Unauthenticated)
    }
    private val alertSoundStore = mockk<AlertSoundStore>(relaxed = true) {
        every { lowAlertSoundName } returns null
        every { highAlertSoundName } returns null
        every { aiNotificationSoundName } returns null
        every { overrideSilentForLowAlerts } returns true
    }
    private val alertNotificationManager = mockk<AlertNotificationManager>(relaxed = true)
    private val pluginRegistry = mockk<PluginRegistry>(relaxed = true) {
        every { availablePlugins } returns MutableStateFlow<List<PluginMetadata>>(emptyList())
        every { activePumpPlugin } returns MutableStateFlow<DevicePlugin?>(null)
        every { allActivePlugins } returns MutableStateFlow<List<Plugin>>(emptyList())
    }

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun createViewModel() =
        SettingsViewModel(appContext, pumpCredentialStore, appSettingsStore, glucoseRangeStore, safetyLimitsStore, authRepository, appUpdateChecker, authManager, alertSoundStore, alertNotificationManager, pluginRegistry)

    @Test
    fun `loadState initializes from stores`() {
        val vm = createViewModel()
        val state = vm.uiState.value

        assertEquals("https://test.example.com", state.baseUrl)
        assertFalse(state.isLoggedIn)
        assertFalse(state.isPumpPaired)
        assertTrue(state.backendSyncEnabled)
        assertEquals(7, state.dataRetentionDays)
    }

    @Test
    fun `loadState restores user email when logged in`() {
        every { authRepository.isLoggedIn() } returns true
        every { authRepository.getUserEmail() } returns "saved@test.com"
        val vm = createViewModel()

        assertTrue(vm.uiState.value.isLoggedIn)
        assertEquals("saved@test.com", vm.uiState.value.userEmail)
    }

    @Test
    fun `saveBaseUrl validates HTTPS via AuthRepository`() {
        every { authRepository.isValidUrl("https://valid.example.com") } returns true
        val vm = createViewModel()
        vm.saveBaseUrl("https://valid.example.com")
        assertEquals("https://valid.example.com", vm.uiState.value.baseUrl)
        verify { authRepository.saveBaseUrl("https://valid.example.com") }
    }

    @Test
    fun `saveBaseUrl trims input`() {
        every { authRepository.isValidUrl("https://example.com") } returns true
        val vm = createViewModel()
        vm.saveBaseUrl("  https://example.com  ")
        verify { authRepository.saveBaseUrl("https://example.com") }
    }

    @Test
    fun `saveBaseUrl does not persist empty string`() {
        val vm = createViewModel()
        vm.saveBaseUrl("")
        verify(exactly = 0) { authRepository.saveBaseUrl(any()) }
    }

    @Test
    fun `saveBaseUrl rejects malformed URL`() {
        every { authRepository.isValidUrl("not-a-url") } returns false
        val vm = createViewModel()
        vm.saveBaseUrl("not-a-url")
        assertEquals("Invalid URL. HTTPS required.", vm.uiState.value.connectionTestResult)
        verify(exactly = 0) { authRepository.saveBaseUrl(any()) }
    }

    @Test
    fun `testConnection shows success via AuthRepository`() = runTest {
        coEvery { authRepository.testConnection() } returns Result.success("Connected successfully")
        val vm = createViewModel()

        vm.testConnection()

        assertEquals("Connected successfully", vm.uiState.value.connectionTestResult)
        assertFalse(vm.uiState.value.isTestingConnection)
    }

    @Test
    fun `testConnection shows error on failure`() = runTest {
        coEvery { authRepository.testConnection() } returns Result.failure(Exception("Connection refused"))
        val vm = createViewModel()

        vm.testConnection()

        assertTrue(vm.uiState.value.connectionTestResult!!.contains("Connection refused"))
    }

    @Test
    fun `testConnection requires URL`() {
        every { authRepository.getBaseUrl() } returns ""
        val vm = createViewModel()

        vm.testConnection()

        assertEquals("Enter a server URL first", vm.uiState.value.connectionTestResult)
    }

    @Test
    fun `login succeeds via AuthRepository`() = runTest {
        coEvery { authRepository.login(any(), any(), any(), any()) } returns LoginResult(
            success = true, email = "user@test.com",
        )
        val vm = createViewModel()

        vm.login("user@test.com", "password123")

        assertTrue(vm.uiState.value.isLoggedIn)
        assertEquals("user@test.com", vm.uiState.value.userEmail)
        assertFalse(vm.uiState.value.isLoggingIn)
        assertNull(vm.uiState.value.loginError)
    }

    @Test
    fun `login shows error on failure`() = runTest {
        coEvery { authRepository.login(any(), any(), any(), any()) } returns LoginResult(
            success = false, error = "Invalid email or password",
        )
        val vm = createViewModel()

        vm.login("user@test.com", "wrongpassword")

        assertFalse(vm.uiState.value.isLoggedIn)
        assertEquals("Invalid email or password", vm.uiState.value.loginError)
    }

    @Test
    fun `login requires URL`() {
        every { authRepository.getBaseUrl() } returns ""
        val vm = createViewModel()

        vm.login("user@test.com", "password")

        assertEquals("Configure server URL first", vm.uiState.value.loginError)
    }

    @Test
    fun `login requires email and password`() {
        val vm = createViewModel()

        vm.login("", "password")
        assertEquals("Email and password are required", vm.uiState.value.loginError)

        vm.login("user@test.com", "")
        assertEquals("Email and password are required", vm.uiState.value.loginError)
    }

    @Test
    fun `logout delegates to AuthRepository and resets onboarding`() {
        every { authRepository.isLoggedIn() } returns true
        val vm = createViewModel()

        vm.logout()

        assertFalse(vm.uiState.value.isLoggedIn)
        assertNull(vm.uiState.value.userEmail)
        verify { authRepository.logout(any()) }
        verify { appSettingsStore.onboardingComplete = false }
    }

    @Test
    fun `logout emits navigateToOnboarding event`() = runTest {
        every { authRepository.isLoggedIn() } returns true
        val vm = createViewModel()

        vm.logout()

        // Channel-backed flow should deliver the event
        withTimeout(1000) {
            vm.navigateToOnboarding.first()
        }
    }

    @Test
    fun `unpair clears pump credentials`() {
        every { pumpCredentialStore.isPaired() } returns true
        every { pumpCredentialStore.getPairedAddress() } returns "AA:BB:CC:DD:EE:FF"
        val vm = createViewModel()
        assertTrue(vm.uiState.value.isPumpPaired)

        vm.unpair()

        assertFalse(vm.uiState.value.isPumpPaired)
        assertNull(vm.uiState.value.pairedPumpAddress)
        verify { pumpCredentialStore.clearPairing() }
    }

    @Test
    fun `setBackendSyncEnabled persists to store`() {
        val vm = createViewModel()

        vm.setBackendSyncEnabled(false)

        assertFalse(vm.uiState.value.backendSyncEnabled)
        verify { appSettingsStore.backendSyncEnabled = false }
    }

    @Test
    fun `setDataRetentionDays clamps to range`() {
        val vm = createViewModel()

        vm.setDataRetentionDays(0) // below min
        assertEquals(1, vm.uiState.value.dataRetentionDays)

        vm.setDataRetentionDays(50) // above max
        assertEquals(30, vm.uiState.value.dataRetentionDays)

        vm.setDataRetentionDays(14) // valid
        assertEquals(14, vm.uiState.value.dataRetentionDays)
    }

    @Test
    fun `show and dismiss logout confirm`() {
        val vm = createViewModel()

        vm.showLogoutConfirm()
        assertTrue(vm.uiState.value.showLogoutConfirm)

        vm.dismissLogoutConfirm()
        assertFalse(vm.uiState.value.showLogoutConfirm)
    }

    @Test
    fun `show and dismiss unpair confirm`() {
        val vm = createViewModel()

        vm.showUnpairConfirm()
        assertTrue(vm.uiState.value.showUnpairConfirm)

        vm.dismissUnpairConfirm()
        assertFalse(vm.uiState.value.showUnpairConfirm)
    }

    @Test
    fun `checkForUpdate shows available when newer version exists`() = runTest {
        coEvery { appUpdateChecker.check(any()) } returns UpdateCheckResult.UpdateAvailable(
            UpdateInfo(
                latestVersion = "1.0.0",
                latestVersionCode = 1_000_000,
                downloadUrl = "https://github.com/releases/download/v1.0.0/GlycemicGPT-1.0.0-release.apk",
                releaseNotes = "Bug fixes",
                apkSizeBytes = 5_000_000,
            ),
        )
        val vm = createViewModel()

        vm.checkForUpdate()

        val state = vm.uiState.value.updateState
        assertTrue(state is UpdateUiState.Available)
        assertEquals("1.0.0", (state as UpdateUiState.Available).version)
    }

    @Test
    fun `checkForUpdate shows up to date`() = runTest {
        coEvery { appUpdateChecker.check(any()) } returns UpdateCheckResult.UpToDate
        val vm = createViewModel()

        vm.checkForUpdate()

        assertTrue(vm.uiState.value.updateState is UpdateUiState.UpToDate)
    }

    @Test
    fun `checkForUpdate shows error on failure`() = runTest {
        coEvery { appUpdateChecker.check(any()) } returns UpdateCheckResult.Error("Network error")
        val vm = createViewModel()

        vm.checkForUpdate()

        val state = vm.uiState.value.updateState
        assertTrue(state is UpdateUiState.Error)
        assertEquals("Network error", (state as UpdateUiState.Error).message)
    }

    @Test
    fun `downloadAndInstallUpdate transitions to ready on success`() = runTest {
        val apkFile = File("/tmp/test.apk")
        coEvery { appUpdateChecker.downloadApk(any(), any(), any()) } returns DownloadResult.Success(apkFile)
        val vm = createViewModel()

        vm.downloadAndInstallUpdate("https://example.com/test.apk", 5_000_000)

        val state = vm.uiState.value.updateState
        assertTrue(state is UpdateUiState.ReadyToInstall)
        assertEquals(apkFile, (state as UpdateUiState.ReadyToInstall).apkFile)
    }

    @Test
    fun `downloadAndInstallUpdate shows error on failure`() = runTest {
        coEvery { appUpdateChecker.downloadApk(any(), any(), any()) } returns DownloadResult.Error("Download failed")
        val vm = createViewModel()

        vm.downloadAndInstallUpdate("https://example.com/test.apk", 5_000_000)

        val state = vm.uiState.value.updateState
        assertTrue(state is UpdateUiState.Error)
        assertEquals("Download failed", (state as UpdateUiState.Error).message)
    }

    @Test
    fun `dismissUpdateState resets to idle`() {
        val vm = createViewModel()

        vm.dismissUpdateState()

        assertTrue(vm.uiState.value.updateState is UpdateUiState.Idle)
    }

    @Test
    fun `isBatteryOptimized defaults to true when not exempt`() {
        every { powerManager.isIgnoringBatteryOptimizations(any()) } returns false
        val vm = createViewModel()
        assertTrue(vm.uiState.value.isBatteryOptimized)
    }

    @Test
    fun `isBatteryOptimized is false when exempt`() {
        every { powerManager.isIgnoringBatteryOptimizations(any()) } returns true
        val vm = createViewModel()
        assertFalse(vm.uiState.value.isBatteryOptimized)
    }

    @Test
    fun `authState is exposed from AuthManager`() {
        val vm = createViewModel()
        assertEquals(AuthState.Unauthenticated, vm.authState.value)
    }
}
