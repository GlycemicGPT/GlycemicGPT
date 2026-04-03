package com.glycemicgpt.mobile.presentation.onboarding

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.repository.AuthRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class OnboardingUiState(
    val baseUrl: String = "",
    val isTestingConnection: Boolean = false,
    val connectionTestResult: String? = null,
    val connectionTestSuccess: Boolean = false,
    val email: String = "",
    val password: String = "",
    val isLoggingIn: Boolean = false,
    val loginError: String? = null,
    val onboardingComplete: Boolean = false,
    val requestNotificationPermission: Boolean = false,
)

@HiltViewModel
class OnboardingViewModel @Inject constructor(
    private val authRepository: AuthRepository,
    private val appSettingsStore: AppSettingsStore,
) : ViewModel() {

    private val _uiState = MutableStateFlow(OnboardingUiState())
    val uiState: StateFlow<OnboardingUiState> = _uiState.asStateFlow()

    /** Minimum interval between connection tests to prevent server hammering. */
    private var lastConnectionTestMs = 0L

    init {
        // Pre-fill server URL if returning after logout
        val savedUrl = authRepository.getBaseUrl()
        if (!savedUrl.isNullOrBlank()) {
            _uiState.update { it.copy(baseUrl = savedUrl) }
        }
    }

    fun updateBaseUrl(url: String) {
        _uiState.update {
            it.copy(
                baseUrl = url,
                connectionTestResult = null,
                connectionTestSuccess = false,
            )
        }
    }

    fun testConnection() {
        if (_uiState.value.isTestingConnection) return

        val url = _uiState.value.baseUrl.trim()
        if (url.isBlank()) {
            _uiState.update {
                it.copy(
                    connectionTestResult = "Enter a server URL first",
                    connectionTestSuccess = false,
                )
            }
            return
        }
        if (!authRepository.isValidUrl(url)) {
            _uiState.update {
                it.copy(
                    connectionTestResult = "Invalid URL. HTTPS required.",
                    connectionTestSuccess = false,
                )
            }
            return
        }

        // Debounce: minimum 1 second between connection tests (after validation)
        val now = System.currentTimeMillis()
        if (now - lastConnectionTestMs < 1_000L) return
        lastConnectionTestMs = now

        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isTestingConnection = true,
                    connectionTestResult = null,
                    connectionTestSuccess = false,
                )
            }
            // Save URL temporarily so BaseUrlInterceptor routes to it for the test;
            // preserve the previous URL so we can restore it on failure.
            val previousUrl = authRepository.getBaseUrl()
            authRepository.saveBaseUrl(url)
            val result = authRepository.testConnection()
            result.onSuccess { message ->
                // URL already saved above; connection confirmed
                _uiState.update {
                    it.copy(
                        isTestingConnection = false,
                        connectionTestResult = message,
                        connectionTestSuccess = true,
                    )
                }
            }.onFailure { e ->
                // Restore previous known-good URL on failure
                if (!previousUrl.isNullOrBlank()) {
                    authRepository.saveBaseUrl(previousUrl)
                }
                _uiState.update {
                    it.copy(
                        isTestingConnection = false,
                        connectionTestResult = "Connection failed: ${e.message ?: "Unknown error"}",
                        connectionTestSuccess = false,
                    )
                }
            }
        }
    }

    fun updateEmail(email: String) {
        _uiState.update { it.copy(email = email, loginError = null) }
    }

    fun updatePassword(password: String) {
        _uiState.update { it.copy(password = password, loginError = null) }
    }

    fun login() {
        val snapshot = _uiState.value
        if (snapshot.isLoggingIn) return
        if (snapshot.email.isBlank() || snapshot.password.isBlank()) {
            _uiState.update { it.copy(loginError = "Email and password are required") }
            return
        }

        viewModelScope.launch {
            _uiState.update { it.copy(isLoggingIn = true, loginError = null) }
            val result = authRepository.login(
                snapshot.baseUrl.trim(),
                snapshot.email.trim(),
                snapshot.password,
                viewModelScope,
            )
            if (result.success) {
                appSettingsStore.onboardingComplete = true
                // Request notification permission first; onboardingComplete is set
                // after permission is handled to avoid racing the navigation transition
                _uiState.update {
                    it.copy(
                        isLoggingIn = false,
                        password = "",
                        requestNotificationPermission = true,
                    )
                }
            } else {
                _uiState.update {
                    it.copy(
                        isLoggingIn = false,
                        loginError = result.error,
                        password = "",
                    )
                }
            }
        }
    }

    fun onNotificationPermissionHandled() {
        _uiState.update {
            it.copy(
                requestNotificationPermission = false,
                onboardingComplete = true,
            )
        }
    }

    /**
     * Returns the starting page index for fresh install vs returning after logout.
     * Returning users (have a saved URL) skip to the server page, but only if they
     * previously completed onboarding (ensuring they saw the safety disclaimer).
     */
    fun getStartPage(): Int {
        val savedUrl = authRepository.getBaseUrl()
        val completedBefore = appSettingsStore.onboardingComplete
        return if (!savedUrl.isNullOrBlank() && completedBefore) {
            OnboardingPages.SERVER
        } else {
            OnboardingPages.WELCOME
        }
    }
}
