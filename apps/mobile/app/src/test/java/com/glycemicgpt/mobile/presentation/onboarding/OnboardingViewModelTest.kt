package com.glycemicgpt.mobile.presentation.onboarding

import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.repository.AuthRepository
import com.glycemicgpt.mobile.data.repository.LoginResult
import io.mockk.coEvery
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class OnboardingViewModelTest {

    private val testDispatcher = UnconfinedTestDispatcher()
    private val authRepository = mockk<AuthRepository>(relaxed = true) {
        every { getBaseUrl() } returns null
        every { isLoggedIn() } returns false
    }
    private val appSettingsStore = mockk<AppSettingsStore>(relaxed = true)

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun createViewModel() = OnboardingViewModel(authRepository, appSettingsStore)

    @Test
    fun `initial state has empty defaults`() {
        val vm = createViewModel()
        val state = vm.uiState.value

        assertEquals("", state.baseUrl)
        assertFalse(state.isTestingConnection)
        assertNull(state.connectionTestResult)
        assertFalse(state.connectionTestSuccess)
        assertEquals("", state.email)
        assertEquals("", state.password)
        assertFalse(state.isLoggingIn)
        assertNull(state.loginError)
        assertFalse(state.onboardingComplete)
    }

    @Test
    fun `pre-fills baseUrl from token store`() {
        every { authRepository.getBaseUrl() } returns "https://saved.example.com"
        val vm = createViewModel()

        assertEquals("https://saved.example.com", vm.uiState.value.baseUrl)
    }

    @Test
    fun `getStartPage returns WELCOME for fresh install`() {
        every { authRepository.getBaseUrl() } returns null
        val vm = createViewModel()

        assertEquals(OnboardingPages.WELCOME, vm.getStartPage())
    }

    @Test
    fun `getStartPage returns SERVER for returning user who completed onboarding`() {
        every { authRepository.getBaseUrl() } returns "https://saved.example.com"
        every { appSettingsStore.onboardingComplete } returns true
        val vm = createViewModel()

        assertEquals(OnboardingPages.SERVER, vm.getStartPage())
    }

    @Test
    fun `getStartPage returns WELCOME when saved URL exists but onboarding not completed`() {
        every { authRepository.getBaseUrl() } returns "https://saved.example.com"
        every { appSettingsStore.onboardingComplete } returns false
        val vm = createViewModel()

        assertEquals(OnboardingPages.WELCOME, vm.getStartPage())
    }

    @Test
    fun `updateBaseUrl clears connection result`() {
        val vm = createViewModel()
        vm.updateBaseUrl("https://new.example.com")

        assertEquals("https://new.example.com", vm.uiState.value.baseUrl)
        assertNull(vm.uiState.value.connectionTestResult)
        assertFalse(vm.uiState.value.connectionTestSuccess)
    }

    @Test
    fun `testConnection success sets connectionTestSuccess`() = runTest {
        every { authRepository.isValidUrl(any()) } returns true
        coEvery { authRepository.testConnection() } returns Result.success("Connected successfully")
        val vm = createViewModel()
        vm.updateBaseUrl("https://test.example.com")

        vm.testConnection()

        assertTrue(vm.uiState.value.connectionTestSuccess)
        assertEquals("Connected successfully", vm.uiState.value.connectionTestResult)
        assertFalse(vm.uiState.value.isTestingConnection)
    }

    @Test
    fun `testConnection failure clears connectionTestSuccess`() = runTest {
        every { authRepository.isValidUrl(any()) } returns true
        coEvery { authRepository.testConnection() } returns Result.failure(Exception("Connection refused"))
        val vm = createViewModel()
        vm.updateBaseUrl("https://test.example.com")

        vm.testConnection()

        assertFalse(vm.uiState.value.connectionTestSuccess)
        assertTrue(vm.uiState.value.connectionTestResult!!.contains("Connection refused"))
        assertFalse(vm.uiState.value.isTestingConnection)
    }

    @Test
    fun `testConnection rejects blank URL`() {
        val vm = createViewModel()
        vm.testConnection()

        assertEquals("Enter a server URL first", vm.uiState.value.connectionTestResult)
        assertFalse(vm.uiState.value.connectionTestSuccess)
    }

    @Test
    fun `testConnection rejects invalid URL`() {
        every { authRepository.isValidUrl("not-a-url") } returns false
        val vm = createViewModel()
        vm.updateBaseUrl("not-a-url")

        vm.testConnection()

        assertEquals("Invalid URL. HTTPS required.", vm.uiState.value.connectionTestResult)
        assertFalse(vm.uiState.value.connectionTestSuccess)
    }

    @Test
    fun `login success requests notification permission before completing onboarding`() = runTest {
        every { authRepository.isValidUrl(any()) } returns true
        coEvery { authRepository.login(any(), any(), any(), any()) } returns LoginResult(
            success = true, email = "user@test.com",
        )
        val vm = createViewModel()
        vm.updateBaseUrl("https://test.example.com")
        vm.updateEmail("user@test.com")
        vm.updatePassword("password123")

        vm.login()

        // After login, notification permission is requested but onboarding isn't complete yet
        assertTrue(vm.uiState.value.requestNotificationPermission)
        assertFalse(vm.uiState.value.onboardingComplete)
        assertFalse(vm.uiState.value.isLoggingIn)
        assertNull(vm.uiState.value.loginError)
        assertEquals("", vm.uiState.value.password)
        verify { appSettingsStore.onboardingComplete = true }
    }

    @Test
    fun `onNotificationPermissionHandled completes onboarding`() = runTest {
        every { authRepository.isValidUrl(any()) } returns true
        coEvery { authRepository.login(any(), any(), any(), any()) } returns LoginResult(
            success = true, email = "user@test.com",
        )
        val vm = createViewModel()
        vm.updateBaseUrl("https://test.example.com")
        vm.updateEmail("user@test.com")
        vm.updatePassword("password123")

        vm.login()
        assertTrue(vm.uiState.value.requestNotificationPermission)
        assertFalse(vm.uiState.value.onboardingComplete)

        vm.onNotificationPermissionHandled()

        assertFalse(vm.uiState.value.requestNotificationPermission)
        assertTrue(vm.uiState.value.onboardingComplete)
    }

    @Test
    fun `login failure shows error`() = runTest {
        coEvery { authRepository.login(any(), any(), any(), any()) } returns LoginResult(
            success = false, error = "Invalid email or password",
        )
        val vm = createViewModel()
        vm.updateBaseUrl("https://test.example.com")
        vm.updateEmail("user@test.com")
        vm.updatePassword("wrong")

        vm.login()

        assertFalse(vm.uiState.value.onboardingComplete)
        assertEquals("Invalid email or password", vm.uiState.value.loginError)
        assertEquals("", vm.uiState.value.password)
    }

    @Test
    fun `login requires email and password`() {
        val vm = createViewModel()
        vm.updateBaseUrl("https://test.example.com")

        vm.login()

        assertEquals("Email and password are required", vm.uiState.value.loginError)
    }

    @Test
    fun `updateEmail clears login error`() {
        val vm = createViewModel()
        vm.login() // triggers error
        assertEquals("Email and password are required", vm.uiState.value.loginError)

        vm.updateEmail("test@example.com")
        assertNull(vm.uiState.value.loginError)
    }

    @Test
    fun `updatePassword clears login error`() {
        val vm = createViewModel()
        vm.login() // triggers error

        vm.updatePassword("newpass")
        assertNull(vm.uiState.value.loginError)
    }
}
