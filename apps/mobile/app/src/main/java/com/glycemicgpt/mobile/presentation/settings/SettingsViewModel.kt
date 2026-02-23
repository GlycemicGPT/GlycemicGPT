package com.glycemicgpt.mobile.presentation.settings

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.PowerManager
import android.provider.Settings
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.glycemicgpt.mobile.BuildConfig
import com.glycemicgpt.mobile.data.auth.AuthManager
import com.glycemicgpt.mobile.data.auth.AuthState
import com.glycemicgpt.mobile.data.local.AlertSoundCategory
import com.glycemicgpt.mobile.data.local.AlertSoundStore
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.local.GlucoseRangeStore
import com.glycemicgpt.mobile.data.local.PumpCredentialStore
import com.glycemicgpt.mobile.data.local.SafetyLimitsStore
import com.glycemicgpt.mobile.data.repository.AuthRepository
import com.glycemicgpt.mobile.data.update.AppUpdateChecker
import com.glycemicgpt.mobile.service.AlertNotificationManager
import com.glycemicgpt.mobile.service.AlertStreamService
import com.glycemicgpt.mobile.service.PumpConnectionService
import android.media.RingtoneManager
import com.glycemicgpt.mobile.data.update.DownloadResult
import com.glycemicgpt.mobile.data.update.UpdateCheckResult
import com.glycemicgpt.mobile.wear.WearDataContract
import com.google.android.gms.wearable.CapabilityClient
import com.google.android.gms.wearable.Wearable
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.io.File
import javax.inject.Inject

private const val DEFAULT_ALARM_NAME = "Default Alarm"
private const val DEFAULT_NOTIFICATION_NAME = "Default Notification"

sealed class UpdateUiState {
    object Idle : UpdateUiState()
    object Checking : UpdateUiState()
    data class Available(
        val version: String,
        val downloadUrl: String,
        val releaseNotes: String?,
        val sizeBytes: Long,
    ) : UpdateUiState()
    object UpToDate : UpdateUiState()
    object Downloading : UpdateUiState()
    data class ReadyToInstall(val apkFile: File) : UpdateUiState()
    data class Error(val message: String) : UpdateUiState()
}

data class SettingsUiState(
    // Account
    val baseUrl: String = "",
    val isLoggedIn: Boolean = false,
    val userEmail: String? = null,
    // Pump
    val isPumpPaired: Boolean = false,
    val pairedPumpAddress: String? = null,
    // Sync
    val backendSyncEnabled: Boolean = true,
    val dataRetentionDays: Int = 7,
    // About
    val appVersion: String = "",
    val buildType: String = "",
    // Connection test
    val isTestingConnection: Boolean = false,
    val connectionTestResult: String? = null,
    // Login
    val isLoggingIn: Boolean = false,
    val loginError: String? = null,
    // Confirmation dialogs
    val showLogoutConfirm: Boolean = false,
    val showUnpairConfirm: Boolean = false,
    // App update
    val updateState: UpdateUiState = UpdateUiState.Idle,
    // Watch
    val watchAppInstalled: Boolean? = null,
    val watchConnected: Boolean = false,
    // Battery optimization
    val isBatteryOptimized: Boolean = true,
    // Notification sounds
    val lowAlertSoundName: String = DEFAULT_ALARM_NAME,
    val lowAlertSoundUri: String? = null,
    val highAlertSoundName: String = DEFAULT_NOTIFICATION_NAME,
    val highAlertSoundUri: String? = null,
    val aiNotificationSoundName: String = DEFAULT_NOTIFICATION_NAME,
    val aiNotificationSoundUri: String? = null,
    val overrideSilentForLow: Boolean = true,
)

@HiltViewModel
class SettingsViewModel @Inject constructor(
    @ApplicationContext private val appContext: Context,
    private val pumpCredentialStore: PumpCredentialStore,
    private val appSettingsStore: AppSettingsStore,
    private val glucoseRangeStore: GlucoseRangeStore,
    private val safetyLimitsStore: SafetyLimitsStore,
    private val authRepository: AuthRepository,
    private val appUpdateChecker: AppUpdateChecker,
    private val authManager: AuthManager,
    private val alertSoundStore: AlertSoundStore,
    private val alertNotificationManager: AlertNotificationManager,
) : ViewModel() {

    private val _uiState = MutableStateFlow(SettingsUiState())
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    /** Observable auth state for UI-level session expiry handling. */
    val authState: StateFlow<AuthState> = authManager.authState

    /** One-shot event to navigate to onboarding after logout. */
    private val _navigateToOnboarding = Channel<Unit>(Channel.CONFLATED)
    val navigateToOnboarding = _navigateToOnboarding.receiveAsFlow()

    init {
        loadState()

        // Re-load state when auth status changes (e.g. login from onboarding).
        // drop(1) skips the initial emission (already handled by loadState() above),
        // distinctUntilChanged avoids redundant reloads on duplicate state emissions.
        viewModelScope.launch {
            authManager.authState.drop(1).distinctUntilChanged().collect { loadState() }
        }
    }

    fun loadState() {
        val loggedIn = authRepository.isLoggedIn()
        _uiState.value = _uiState.value.copy(
            baseUrl = authRepository.getBaseUrl() ?: "",
            isLoggedIn = loggedIn,
            userEmail = if (loggedIn) authRepository.getUserEmail() else null,
            isPumpPaired = pumpCredentialStore.isPaired(),
            pairedPumpAddress = pumpCredentialStore.getPairedAddress(),
            backendSyncEnabled = appSettingsStore.backendSyncEnabled,
            dataRetentionDays = appSettingsStore.dataRetentionDays,
            appVersion = BuildConfig.VERSION_NAME,
            buildType = BuildConfig.BUILD_TYPE,
            lowAlertSoundName = alertSoundStore.lowAlertSoundName ?: DEFAULT_ALARM_NAME,
            lowAlertSoundUri = alertSoundStore.lowAlertSoundUri,
            highAlertSoundName = alertSoundStore.highAlertSoundName ?: DEFAULT_NOTIFICATION_NAME,
            highAlertSoundUri = alertSoundStore.highAlertSoundUri,
            aiNotificationSoundName = alertSoundStore.aiNotificationSoundName ?: DEFAULT_NOTIFICATION_NAME,
            aiNotificationSoundUri = alertSoundStore.aiNotificationSoundUri,
            overrideSilentForLow = alertSoundStore.overrideSilentForLowAlerts,
        )

        checkBatteryOptimization()

        // Start services on app startup if conditions are met
        if (loggedIn) {
            AlertStreamService.start(appContext)
            viewModelScope.launch { authRepository.reRegisterDevice() }
            if (glucoseRangeStore.isStale()) {
                viewModelScope.launch { authRepository.refreshGlucoseRange() }
            }
            if (safetyLimitsStore.isStale()) {
                viewModelScope.launch { authRepository.refreshSafetyLimits() }
            }
        }
        if (pumpCredentialStore.isPaired()) {
            PumpConnectionService.start(appContext)
        }
    }

    fun saveBaseUrl(url: String) {
        val trimmed = url.trim()
        if (trimmed.isEmpty()) {
            _uiState.value = _uiState.value.copy(baseUrl = trimmed, connectionTestResult = null)
            return
        }
        if (!authRepository.isValidUrl(trimmed)) {
            _uiState.value = _uiState.value.copy(
                connectionTestResult = "Invalid URL. HTTPS required.",
            )
            return
        }
        authRepository.saveBaseUrl(trimmed)
        _uiState.value = _uiState.value.copy(
            baseUrl = trimmed,
            connectionTestResult = null,
        )
    }

    fun testConnection() {
        val url = _uiState.value.baseUrl
        if (url.isBlank()) {
            _uiState.value = _uiState.value.copy(
                connectionTestResult = "Enter a server URL first",
            )
            return
        }

        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(
                isTestingConnection = true,
                connectionTestResult = null,
            )
            val result = authRepository.testConnection()
            result.onSuccess { message ->
                _uiState.value = _uiState.value.copy(
                    isTestingConnection = false,
                    connectionTestResult = message,
                )
            }.onFailure { e ->
                _uiState.value = _uiState.value.copy(
                    isTestingConnection = false,
                    connectionTestResult = "Connection failed: ${e.message}",
                )
            }
        }
    }

    fun login(email: String, password: String) {
        val url = _uiState.value.baseUrl
        if (url.isBlank()) {
            _uiState.value = _uiState.value.copy(loginError = "Configure server URL first")
            return
        }
        if (email.isBlank() || password.isBlank()) {
            _uiState.value = _uiState.value.copy(loginError = "Email and password are required")
            return
        }
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoggingIn = true, loginError = null)
            val result = authRepository.login(url, email, password, viewModelScope)
            if (result.success) {
                _uiState.value = _uiState.value.copy(
                    isLoggingIn = false,
                    isLoggedIn = true,
                    userEmail = result.email,
                )
            } else {
                _uiState.value = _uiState.value.copy(
                    isLoggingIn = false,
                    loginError = result.error,
                )
            }
        }
    }

    fun showLogoutConfirm() {
        _uiState.value = _uiState.value.copy(showLogoutConfirm = true)
    }

    fun dismissLogoutConfirm() {
        _uiState.value = _uiState.value.copy(showLogoutConfirm = false)
    }

    fun logout() {
        PumpConnectionService.stop(appContext)
        authRepository.logout(viewModelScope)
        appSettingsStore.onboardingComplete = false
        _uiState.value = _uiState.value.copy(
            isLoggedIn = false,
            userEmail = null,
            showLogoutConfirm = false,
        )
        _navigateToOnboarding.trySend(Unit)
    }

    fun showUnpairConfirm() {
        _uiState.value = _uiState.value.copy(showUnpairConfirm = true)
    }

    fun dismissUnpairConfirm() {
        _uiState.value = _uiState.value.copy(showUnpairConfirm = false)
    }

    fun unpair() {
        pumpCredentialStore.clearPairing()
        _uiState.value = _uiState.value.copy(
            isPumpPaired = false,
            pairedPumpAddress = null,
            showUnpairConfirm = false,
        )
    }

    fun setBackendSyncEnabled(enabled: Boolean) {
        appSettingsStore.backendSyncEnabled = enabled
        _uiState.value = _uiState.value.copy(backendSyncEnabled = enabled)
    }

    fun setDataRetentionDays(days: Int) {
        val clamped = days.coerceIn(AppSettingsStore.MIN_RETENTION_DAYS, AppSettingsStore.MAX_RETENTION_DAYS)
        appSettingsStore.dataRetentionDays = clamped
        _uiState.value = _uiState.value.copy(dataRetentionDays = clamped)
    }

    fun clearConnectionTestResult() {
        _uiState.value = _uiState.value.copy(connectionTestResult = null)
    }

    fun clearLoginError() {
        _uiState.value = _uiState.value.copy(loginError = null)
    }

    fun checkForUpdate() {
        if (_uiState.value.updateState is UpdateUiState.Checking) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(updateState = UpdateUiState.Checking)
            when (val result = appUpdateChecker.check(BuildConfig.VERSION_CODE)) {
                is UpdateCheckResult.UpdateAvailable -> {
                    _uiState.value = _uiState.value.copy(
                        updateState = UpdateUiState.Available(
                            version = result.info.latestVersion,
                            downloadUrl = result.info.downloadUrl,
                            releaseNotes = result.info.releaseNotes,
                            sizeBytes = result.info.apkSizeBytes,
                        ),
                    )
                }
                is UpdateCheckResult.UpToDate -> {
                    _uiState.value = _uiState.value.copy(
                        updateState = UpdateUiState.UpToDate,
                    )
                }
                is UpdateCheckResult.Error -> {
                    _uiState.value = _uiState.value.copy(
                        updateState = UpdateUiState.Error(result.message),
                    )
                }
            }
        }
    }

    fun downloadAndInstallUpdate(url: String, expectedSize: Long) {
        if (_uiState.value.updateState is UpdateUiState.Downloading) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(updateState = UpdateUiState.Downloading)
            val fileName = url.substringAfterLast("/")
            when (val result = appUpdateChecker.downloadApk(url, fileName, expectedSize)) {
                is DownloadResult.Success -> {
                    _uiState.value = _uiState.value.copy(
                        updateState = UpdateUiState.ReadyToInstall(result.apkFile),
                    )
                }
                is DownloadResult.Error -> {
                    _uiState.value = _uiState.value.copy(
                        updateState = UpdateUiState.Error(result.message),
                    )
                }
            }
        }
    }

    fun getInstallIntent(apkFile: File): android.content.Intent {
        return appUpdateChecker.createInstallIntent(apkFile)
    }

    fun dismissUpdateState() {
        _uiState.value = _uiState.value.copy(updateState = UpdateUiState.Idle)
    }

    fun checkWatchStatus() {
        viewModelScope.launch {
            try {
                val capInfo = Wearable.getCapabilityClient(appContext)
                    .getCapability(
                        WearDataContract.WATCH_APP_CAPABILITY,
                        CapabilityClient.FILTER_ALL,
                    )
                    .await()
                val reachable = capInfo.nodes.any { it.isNearby }
                _uiState.value = _uiState.value.copy(
                    watchAppInstalled = capInfo.nodes.isNotEmpty(),
                    watchConnected = reachable,
                )
            } catch (e: Exception) {
                Timber.w(e, "Failed to check watch status")
                _uiState.value = _uiState.value.copy(
                    watchAppInstalled = null,
                    watchConnected = false,
                )
            }
        }
    }

    fun checkBatteryOptimization() {
        val pm = appContext.getSystemService(Context.POWER_SERVICE) as PowerManager
        val isIgnoring = pm.isIgnoringBatteryOptimizations(appContext.packageName)
        _uiState.value = _uiState.value.copy(isBatteryOptimized = !isIgnoring)
    }

    fun createBatteryOptimizationIntent(): Intent {
        return Intent(
            Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
            Uri.parse("package:${appContext.packageName}"),
        )
    }

    fun onSoundSelected(category: AlertSoundCategory, uri: Uri?) {
        viewModelScope.launch {
            // null URI from the ringtone picker means "Silent" was selected.
            // For AI notifications (which offer a silent option), store the sentinel;
            // for low/high alerts, null means "reset to default".
            val isSilent = uri == null && category == AlertSoundCategory.AI_NOTIFICATION

            val (validatedUri, displayName) = withContext(Dispatchers.IO) {
                if (isSilent) {
                    null to "Silent"
                } else if (uri != null) {
                    try {
                        val ringtone = RingtoneManager.getRingtone(appContext, uri)
                        if (ringtone != null) {
                            val title = ringtone.getTitle(appContext) ?: defaultSoundName(category)
                            ringtone.stop()
                            uri to title
                        } else {
                            null to defaultSoundName(category)
                        }
                    } catch (_: Exception) {
                        null to defaultSoundName(category)
                    }
                } else {
                    null to defaultSoundName(category)
                }
            }

            val uriString = when {
                isSilent -> AlertSoundStore.SILENT_URI
                else -> validatedUri?.toString()
            }

            withContext(Dispatchers.IO) {
                alertSoundStore.setSoundUri(category, uriString)
                alertSoundStore.setSoundName(category, displayName)

                // Take persistable URI permission so the sound survives reboots
                if (validatedUri != null) {
                    try {
                        appContext.contentResolver.takePersistableUriPermission(
                            validatedUri,
                            Intent.FLAG_GRANT_READ_URI_PERMISSION,
                        )
                    } catch (_: SecurityException) {
                        // Some ringtone URIs don't support persistable permissions
                    }
                }

                alertNotificationManager.recreateChannel(category)
            }

            _uiState.value = when (category) {
                AlertSoundCategory.LOW_ALERT ->
                    _uiState.value.copy(lowAlertSoundName = displayName, lowAlertSoundUri = uriString)
                AlertSoundCategory.HIGH_ALERT ->
                    _uiState.value.copy(highAlertSoundName = displayName, highAlertSoundUri = uriString)
                AlertSoundCategory.AI_NOTIFICATION ->
                    _uiState.value.copy(aiNotificationSoundName = displayName, aiNotificationSoundUri = uriString)
            }
        }
    }

    private fun defaultSoundName(category: AlertSoundCategory): String = when (category) {
        AlertSoundCategory.LOW_ALERT -> DEFAULT_ALARM_NAME
        AlertSoundCategory.HIGH_ALERT, AlertSoundCategory.AI_NOTIFICATION -> DEFAULT_NOTIFICATION_NAME
    }

    fun setOverrideSilentForLow(enabled: Boolean) {
        alertSoundStore.overrideSilentForLowAlerts = enabled
        _uiState.value = _uiState.value.copy(overrideSilentForLow = enabled)
    }
}
