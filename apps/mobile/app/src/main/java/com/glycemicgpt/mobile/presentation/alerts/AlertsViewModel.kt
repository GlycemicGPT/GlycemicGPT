package com.glycemicgpt.mobile.presentation.alerts

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.local.entity.AlertEntity
import com.glycemicgpt.mobile.data.network.NetworkMonitor
import com.glycemicgpt.mobile.data.repository.AlertRepository
import com.glycemicgpt.mobile.domain.model.GlucoseUnit
import com.glycemicgpt.mobile.service.AlertNotificationManager
import com.glycemicgpt.mobile.service.AlertStreamStateHolder
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import timber.log.Timber
import java.io.IOException
import javax.inject.Inject

data class AlertsUiState(
    val isLoading: Boolean = false,
    /** User-facing failure copy for a refresh/acknowledge, surfaced as a snackbar then cleared.
     *  Never a raw exception message. */
    val error: String? = null,
)

@HiltViewModel
class AlertsViewModel @Inject constructor(
    private val alertRepository: AlertRepository,
    private val alertNotificationManager: AlertNotificationManager,
    private val appSettingsStore: AppSettingsStore,
    networkMonitor: NetworkMonitor,
    alertStreamStateHolder: AlertStreamStateHolder,
) : ViewModel() {

    private val _uiState = MutableStateFlow(AlertsUiState())
    val uiState: StateFlow<AlertsUiState> = _uiState.asStateFlow()

    val alerts: StateFlow<List<AlertEntity>> = alertRepository.observeRecentAlerts()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    /** The user's glucose display unit, for rendering alert values. Alert detection stays mg/dL. */
    val glucoseUnit: StateFlow<GlucoseUnit> = appSettingsStore.glucoseUnitFlow()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), appSettingsStore.glucoseUnit)

    /**
     * Whether server-pushed alerting is degraded (backend unreachable or the alert stream is not
     * connected). Drives the honest [AlertingDegradedBanner] — cached alerts still display, but no
     * new alerts arrive until reconnected.
     */
    val alertingDegraded: StateFlow<Boolean> = combine(
        networkMonitor.status,
        alertStreamStateHolder.state,
    ) { network, stream -> isAlertingDegraded(network, stream) }
        .stateIn(
            viewModelScope,
            SharingStarted.WhileSubscribed(5000),
            // Seed from the real current state, not an optimistic false — a safety banner must
            // never default to "healthy" while the combine spins up.
            isAlertingDegraded(networkMonitor.status.value, alertStreamStateHolder.state.value),
        )

    init {
        viewModelScope.launch { alertRepository.cleanupOldAlerts() }
        refreshAlerts()
    }

    fun refreshAlerts() {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, error = null)
            alertRepository.fetchPendingAlerts()
                .onSuccess {
                    _uiState.value = _uiState.value.copy(isLoading = false)
                }
                .onFailure { e ->
                    Timber.w(e, "Failed to fetch alerts")
                    _uiState.value = _uiState.value.copy(
                        isLoading = false,
                        error = refreshErrorMessage(e),
                    )
                }
        }
    }

    fun acknowledgeAlert(serverId: String) {
        viewModelScope.launch {
            alertRepository.acknowledgeAlert(serverId)
                .onSuccess {
                    alertNotificationManager.markAcknowledged(serverId)
                }
                .onFailure { e ->
                    Timber.w(e, "Failed to acknowledge alert")
                    _uiState.value = _uiState.value.copy(error = acknowledgeErrorMessage(e))
                }
        }
    }

    fun clearError() {
        _uiState.value = _uiState.value.copy(error = null)
    }

    private fun refreshErrorMessage(e: Throwable): String = when (e) {
        // Neutral about cache contents — the list below may be empty.
        is IOException -> "Can't reach your server — alerts may be out of date."
        else -> "Couldn't refresh alerts. Try again."
    }

    private fun acknowledgeErrorMessage(e: Throwable): String = when (e) {
        is IOException -> "Couldn't acknowledge the alert. Check your connection and try again."
        else -> "Couldn't acknowledge the alert. Try again."
    }
}
