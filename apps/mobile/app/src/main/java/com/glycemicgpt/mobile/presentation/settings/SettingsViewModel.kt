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
import com.glycemicgpt.mobile.domain.plugin.PluginMetadata
import com.glycemicgpt.mobile.plugin.PluginRegistry
import com.glycemicgpt.mobile.plugin.RuntimePluginInfo
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
import com.glycemicgpt.mobile.wear.WatchFacePusher
import com.glycemicgpt.mobile.wear.WearDataContract
import com.glycemicgpt.mobile.wear.WearDataSender
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
import kotlinx.coroutines.Job
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import java.util.concurrent.atomic.AtomicBoolean
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

sealed class WatchFacePushState {
    object Idle : WatchFacePushState()
    object Pushing : WatchFacePushState()
    object Success : WatchFacePushState()
    data class Error(val message: String) : WatchFacePushState()
}

data class WatchFaceConfig(
    val showIoB: Boolean = true,
    val showGraph: Boolean = true,
    val showAlert: Boolean = true,
    val showSeconds: Boolean = false,
    val graphRangeHours: Int = 3,
    val theme: WatchFaceTheme = WatchFaceTheme.Dark,
) {
    companion object {
        val VALID_GRAPH_RANGES = listOf(1, 3, 6)
    }
}

enum class WatchFaceTheme(val label: String, val contractKey: String) {
    Dark("Dark", WearDataContract.THEME_DARK),
    ClinicalBlue("Clinical Blue", WearDataContract.THEME_CLINICAL_BLUE),
    HighContrast("High Contrast", WearDataContract.THEME_HIGH_CONTRAST),
}

data class WatchDataTelemetry(
    val lastBgMgDl: Int? = null,
    val lastBgTimestampMs: Long? = null,
    val lastIoB: Float? = null,
    val lastIoBTimestampMs: Long? = null,
    val loadError: String? = null,
)

data class SettingsUiState(
    // Account
    val baseUrl: String = "",
    val isLoggedIn: Boolean = false,
    val userEmail: String? = null,
    // Pump
    val isPumpPaired: Boolean = false,
    val pairedPumpAddress: String? = null,
    // Plugins
    val availablePlugins: List<PluginMetadata> = emptyList(),
    val activePumpPluginId: String? = null,
    val activePluginIds: Set<String> = emptySet(),
    val activePumpPluginName: String? = null,
    val activePumpProtocolDisplay: String? = null,
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
    val showDeactivateConfirm: Boolean = false,
    val pendingDeactivatePluginId: String? = null,
    // Runtime plugins
    val runtimePlugins: List<RuntimePluginInfo> = emptyList(),
    val pluginInstallError: String? = null,
    val showRemovePluginConfirm: Boolean = false,
    val pendingRemovePluginId: String? = null,
    // App update
    val updateState: UpdateUiState = UpdateUiState.Idle,
    // Watch
    val watchAppInstalled: Boolean? = null,
    val watchConnected: Boolean = false,
    val watchDeviceName: String? = null,
    val watchFacePushState: WatchFacePushState = WatchFacePushState.Idle,
    val watchFaceConfig: WatchFaceConfig = WatchFaceConfig(),
    val watchDataTelemetry: WatchDataTelemetry = WatchDataTelemetry(),
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
    // Debug-only
    val showPumpLabels: Boolean = false,
    // Appearance
    val themeMode: com.glycemicgpt.mobile.presentation.theme.ThemeMode =
        com.glycemicgpt.mobile.presentation.theme.ThemeMode.System,
)

private const val AUTO_DISMISS_MS = 5_000L
private const val PUSH_TIMEOUT_MS = 150_000L
private const val TELEMETRY_TIMEOUT_MS = 10_000L

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
    private val pluginRegistry: PluginRegistry,
    private val watchFacePusher: WatchFacePusher,
    private val wearDataSender: WearDataSender,
) : ViewModel() {

    private val _uiState = MutableStateFlow(SettingsUiState())
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    /** Copy active pump plugin display fields from the registry into the state. */
    private fun SettingsUiState.withActivePumpFields(): SettingsUiState {
        val meta = pluginRegistry.activePumpPlugin.value?.metadata
        return copy(
            activePumpPluginId = meta?.id,
            activePumpPluginName = meta?.name,
            activePumpProtocolDisplay = meta?.let { m ->
                m.protocolName?.let { "$it v${m.version}" }
            },
        )
    }

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
        val loggedIn = authRepository.hasActiveSession()
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
            availablePlugins = pluginRegistry.availablePlugins.value,
            activePluginIds = pluginRegistry.allActivePlugins.value.map { it.metadata.id }.toSet(),
            runtimePlugins = pluginRegistry.runtimePlugins.value,
            showPumpLabels = appSettingsStore.showPumpLabels,
            themeMode = appSettingsStore.themeMode,
            watchFaceConfig = loadPersistedWatchFaceConfig(),
        ).withActivePumpFields()

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

    fun activatePlugin(pluginId: String) {
        val result = pluginRegistry.activatePlugin(pluginId)
        if (result.isFailure) {
            Timber.e(result.exceptionOrNull(), "Failed to activate plugin %s", pluginId)
        }
        _uiState.value = _uiState.value.copy(
            activePluginIds = pluginRegistry.allActivePlugins.value.map { it.metadata.id }.toSet(),
        ).withActivePumpFields()
    }

    fun showDeactivateConfirm(pluginId: String) {
        _uiState.value = _uiState.value.copy(
            showDeactivateConfirm = true,
            pendingDeactivatePluginId = pluginId,
        )
    }

    fun dismissDeactivateConfirm() {
        _uiState.value = _uiState.value.copy(
            showDeactivateConfirm = false,
            pendingDeactivatePluginId = null,
        )
    }

    fun confirmDeactivatePlugin() {
        val pluginId = _uiState.value.pendingDeactivatePluginId ?: return
        val result = pluginRegistry.deactivatePlugin(pluginId)
        if (result.isFailure) {
            Timber.e(result.exceptionOrNull(), "Failed to deactivate plugin %s", pluginId)
        }
        _uiState.value = _uiState.value.copy(
            activePluginIds = pluginRegistry.allActivePlugins.value.map { it.metadata.id }.toSet(),
            showDeactivateConfirm = false,
            pendingDeactivatePluginId = null,
        ).withActivePumpFields()
    }

    @Deprecated("Use showDeactivateConfirm for safety", ReplaceWith("showDeactivateConfirm(pluginId)"))
    fun deactivatePlugin(pluginId: String) {
        showDeactivateConfirm(pluginId)
    }

    fun installPlugin(uri: Uri) {
        viewModelScope.launch(Dispatchers.IO) {
            val result = pluginRegistry.installRuntimePlugin(uri)
            withContext(Dispatchers.Main) {
                result.onSuccess {
                    _uiState.value = _uiState.value.copy(
                        availablePlugins = pluginRegistry.availablePlugins.value,
                        activePluginIds = pluginRegistry.allActivePlugins.value.map { it.metadata.id }.toSet(),
                        runtimePlugins = pluginRegistry.runtimePlugins.value,
                        pluginInstallError = null,
                    )
                }.onFailure { e ->
                    _uiState.value = _uiState.value.copy(
                        pluginInstallError = e.message ?: "Failed to install plugin",
                    )
                }
            }
        }
    }

    fun showRemovePluginConfirm(pluginId: String) {
        _uiState.value = _uiState.value.copy(
            showRemovePluginConfirm = true,
            pendingRemovePluginId = pluginId,
        )
    }

    fun dismissRemovePluginConfirm() {
        _uiState.value = _uiState.value.copy(
            showRemovePluginConfirm = false,
            pendingRemovePluginId = null,
        )
    }

    fun confirmRemovePlugin() {
        val pluginId = _uiState.value.pendingRemovePluginId ?: return
        viewModelScope.launch(Dispatchers.IO) {
            val result = pluginRegistry.removeRuntimePlugin(pluginId)
            withContext(Dispatchers.Main) {
                val errorMsg = if (result.isFailure) {
                    Timber.e(result.exceptionOrNull(), "Failed to remove plugin %s", pluginId)
                    result.exceptionOrNull()?.message ?: "Failed to remove plugin"
                } else {
                    null
                }
                _uiState.value = _uiState.value.copy(
                    availablePlugins = pluginRegistry.availablePlugins.value,
                    activePluginIds = pluginRegistry.allActivePlugins.value.map { it.metadata.id }.toSet(),
                    runtimePlugins = pluginRegistry.runtimePlugins.value,
                    pluginInstallError = errorMsg,
                    showRemovePluginConfirm = false,
                    pendingRemovePluginId = null,
                ).withActivePumpFields()
            }
        }
    }

    fun clearPluginInstallError() {
        _uiState.value = _uiState.value.copy(pluginInstallError = null)
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
                var nearbyNode: com.google.android.gms.wearable.Node? = null
                var anyNode: com.google.android.gms.wearable.Node? = null
                var appInstalled = false

                // Try CapabilityClient first (capability-advertised nodes)
                try {
                    val capInfo = withTimeout(5_000L) {
                        Wearable.getCapabilityClient(appContext)
                            .getCapability(
                                WearDataContract.WATCH_APP_CAPABILITY,
                                CapabilityClient.FILTER_ALL,
                            )
                            .await()
                    }
                    nearbyNode = capInfo.nodes.firstOrNull { it.isNearby }
                    anyNode = nearbyNode ?: capInfo.nodes.firstOrNull()
                    appInstalled = capInfo.nodes.isNotEmpty()
                    Timber.d("CapabilityClient: %d nodes, nearby=%s", capInfo.nodes.size, nearbyNode?.displayName)
                } catch (e: kotlinx.coroutines.TimeoutCancellationException) {
                    Timber.w("CapabilityClient timed out")
                } catch (e: Exception) {
                    Timber.w(e, "CapabilityClient lookup failed")
                }

                // Fallback to NodeClient if no capability nodes found
                if (anyNode == null) {
                    try {
                        val nodes = withTimeout(5_000L) {
                            Wearable.getNodeClient(appContext).connectedNodes.await()
                        }
                        Timber.d("NodeClient fallback: %d connected nodes", nodes.size)
                        nearbyNode = nodes.firstOrNull { it.isNearby }
                        anyNode = nearbyNode ?: nodes.firstOrNull()
                        if (anyNode != null) {
                            appInstalled = true
                        }
                    } catch (e: kotlinx.coroutines.TimeoutCancellationException) {
                        Timber.w("NodeClient timed out")
                    } catch (e: Exception) {
                        Timber.w(e, "NodeClient fallback failed")
                    }
                }

                _uiState.value = _uiState.value.copy(
                    watchAppInstalled = appInstalled,
                    watchConnected = nearbyNode != null,
                    watchDeviceName = anyNode?.displayName,
                )
                // Read last-sent data items for telemetry
                if (appInstalled) {
                    loadWatchDataTelemetry()
                }
                // Push current config to watch when connected
                if (nearbyNode != null) {
                    syncWatchFaceConfig(_uiState.value.watchFaceConfig)
                }
            } catch (e: Exception) {
                Timber.w(e, "Failed to check watch status")
                _uiState.value = _uiState.value.copy(
                    watchAppInstalled = null,
                    watchConnected = false,
                    watchDeviceName = null,
                )
            }
        }
    }

    private suspend fun loadWatchDataTelemetry() {
        try {
            withTimeout(TELEMETRY_TIMEOUT_MS) {
            val dataClient = Wearable.getDataClient(appContext)
            var lastBg: Int? = null
            var lastBgTs: Long? = null
            var lastIoB: Float? = null
            var lastIoBTs: Long? = null

            // Read last CGM data item
            val cgmItems = dataClient.getDataItems(
                WearDataContract.dataUri(WearDataContract.CGM_PATH),
            ).await()
            try {
                cgmItems.firstOrNull()?.let { item ->
                    val map = com.google.android.gms.wearable.DataMapItem.fromDataItem(item).dataMap
                    if (map.containsKey(WearDataContract.KEY_CGM_MG_DL)) {
                        val rawBg = map.getInt(WearDataContract.KEY_CGM_MG_DL)
                        lastBg = if (rawBg in 20..500) rawBg else null
                    }
                    if (map.containsKey(WearDataContract.KEY_CGM_TIMESTAMP)) {
                        lastBgTs = map.getLong(WearDataContract.KEY_CGM_TIMESTAMP)
                    }
                }
            } finally {
                cgmItems.release()
            }

            // Read last IoB data item
            val iobItems = dataClient.getDataItems(
                WearDataContract.dataUri(WearDataContract.IOB_PATH),
            ).await()
            try {
                iobItems.firstOrNull()?.let { item ->
                    val map = com.google.android.gms.wearable.DataMapItem.fromDataItem(item).dataMap
                    if (map.containsKey(WearDataContract.KEY_IOB_VALUE)) {
                        lastIoB = map.getFloat(WearDataContract.KEY_IOB_VALUE)
                    }
                    if (map.containsKey(WearDataContract.KEY_IOB_TIMESTAMP)) {
                        lastIoBTs = map.getLong(WearDataContract.KEY_IOB_TIMESTAMP)
                    }
                }
            } finally {
                iobItems.release()
            }

            _uiState.value = _uiState.value.copy(
                watchDataTelemetry = WatchDataTelemetry(
                    lastBgMgDl = lastBg,
                    lastBgTimestampMs = lastBgTs,
                    lastIoB = lastIoB,
                    lastIoBTimestampMs = lastIoBTs,
                ),
            )
            } // withTimeout
        } catch (e: Exception) {
            Timber.w(e, "Failed to load watch data telemetry")
            _uiState.value = _uiState.value.copy(
                watchDataTelemetry = WatchDataTelemetry(
                    loadError = "Could not read watch data",
                ),
            )
        }
    }

    private val pushInProgress = AtomicBoolean(false)
    private var autoDismissJob: Job? = null

    fun pushWatchFace() {
        if (!pushInProgress.compareAndSet(false, true)) return
        autoDismissJob?.cancel()
        autoDismissJob = null
        _uiState.value = _uiState.value.copy(watchFacePushState = WatchFacePushState.Pushing)
        viewModelScope.launch {
            try {
                val result = try {
                    withTimeout(PUSH_TIMEOUT_MS) {
                        watchFacePusher.pushWatchFace()
                    }
                } catch (_: TimeoutCancellationException) {
                    WatchFacePusher.Result.Error("Push timed out")
                } catch (e: kotlin.coroutines.cancellation.CancellationException) {
                    _uiState.value = _uiState.value.copy(
                        watchFacePushState = WatchFacePushState.Idle,
                    )
                    throw e
                } catch (e: Exception) {
                    Timber.e(e, "Unexpected error during watch face push")
                    WatchFacePusher.Result.Error(e.message ?: "Push failed")
                }
                val newState = when (result) {
                    is WatchFacePusher.Result.Success -> WatchFacePushState.Success
                    is WatchFacePusher.Result.Error -> WatchFacePushState.Error(result.message)
                }
                _uiState.value = _uiState.value.copy(watchFacePushState = newState)
                autoDismissJob = viewModelScope.launch {
                    delay(AUTO_DISMISS_MS)
                    dismissWatchFacePushResult()
                }
            } finally {
                pushInProgress.set(false)
            }
        }
    }

    fun dismissWatchFacePushResult() {
        autoDismissJob?.cancel()
        autoDismissJob = null
        _uiState.value = _uiState.value.copy(watchFacePushState = WatchFacePushState.Idle)
    }

    fun updateWatchFaceConfig(config: WatchFaceConfig) {
        val validated = config.copy(
            graphRangeHours = if (config.graphRangeHours in WatchFaceConfig.VALID_GRAPH_RANGES) {
                config.graphRangeHours
            } else {
                3
            },
        )
        _uiState.value = _uiState.value.copy(watchFaceConfig = validated)
        persistWatchFaceConfig(validated)
        syncWatchFaceConfig(validated)
    }

    private fun syncWatchFaceConfig(config: WatchFaceConfig) {
        viewModelScope.launch {
            try {
                wearDataSender.sendWatchFaceConfig(
                    showIoB = config.showIoB,
                    showGraph = config.showGraph,
                    showAlert = config.showAlert,
                    showSeconds = config.showSeconds,
                    graphRangeHours = config.graphRangeHours,
                    theme = config.theme.contractKey,
                )
            } catch (e: Exception) {
                Timber.w(e, "Failed to sync watch face config")
            }
        }
    }

    private fun loadPersistedWatchFaceConfig(): WatchFaceConfig {
        val themeName = appSettingsStore.watchFaceTheme
        val theme = WatchFaceTheme.entries.find { it.label == themeName } ?: WatchFaceTheme.Dark
        val rawGraphRange = appSettingsStore.watchFaceGraphRangeHours
        val graphRange = if (rawGraphRange in WatchFaceConfig.VALID_GRAPH_RANGES) rawGraphRange else 3
        return WatchFaceConfig(
            showIoB = appSettingsStore.watchFaceShowIoB,
            showGraph = appSettingsStore.watchFaceShowGraph,
            showAlert = appSettingsStore.watchFaceShowAlert,
            showSeconds = appSettingsStore.watchFaceShowSeconds,
            graphRangeHours = graphRange,
            theme = theme,
        )
    }

    private fun persistWatchFaceConfig(config: WatchFaceConfig) {
        appSettingsStore.watchFaceShowIoB = config.showIoB
        appSettingsStore.watchFaceShowGraph = config.showGraph
        appSettingsStore.watchFaceShowAlert = config.showAlert
        appSettingsStore.watchFaceShowSeconds = config.showSeconds
        appSettingsStore.watchFaceGraphRangeHours = config.graphRangeHours
        appSettingsStore.watchFaceTheme = config.theme.label
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

    fun setShowPumpLabels(enabled: Boolean) {
        appSettingsStore.showPumpLabels = enabled
        _uiState.value = _uiState.value.copy(showPumpLabels = enabled)
    }

    fun setThemeMode(mode: com.glycemicgpt.mobile.presentation.theme.ThemeMode) {
        appSettingsStore.themeMode = mode
        _uiState.value = _uiState.value.copy(themeMode = mode)
    }

    fun setOverrideSilentForLow(enabled: Boolean) {
        alertSoundStore.overrideSilentForLowAlerts = enabled
        _uiState.value = _uiState.value.copy(overrideSilentForLow = enabled)
    }
}
