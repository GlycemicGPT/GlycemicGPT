package com.glycemicgpt.mobile.presentation.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.glycemicgpt.mobile.data.local.GlucoseRangeStore
import com.glycemicgpt.mobile.data.local.SafetyLimitsStore
import com.glycemicgpt.mobile.data.remote.GlycemicGptApi
import com.glycemicgpt.mobile.data.repository.AuthRepository
import com.glycemicgpt.mobile.data.repository.PumpDataRepository
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BatteryStatus
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.model.ReservoirReading
import com.glycemicgpt.mobile.domain.model.TimeInRangeData
import com.glycemicgpt.mobile.domain.pump.PumpDriver
import com.glycemicgpt.mobile.service.BackendSyncManager
import com.glycemicgpt.mobile.service.PumpPollingOrchestrator
import com.glycemicgpt.mobile.service.SyncStatus
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import timber.log.Timber
import java.time.Instant
import javax.inject.Inject

@OptIn(ExperimentalCoroutinesApi::class)
@HiltViewModel
class HomeViewModel @Inject constructor(
    private val pumpDriver: PumpDriver,
    private val repository: PumpDataRepository,
    private val backendSyncManager: BackendSyncManager,
    private val glucoseRangeStore: GlucoseRangeStore,
    private val safetyLimitsStore: SafetyLimitsStore,
    private val authRepository: AuthRepository,
    private val api: GlycemicGptApi,
) : ViewModel() {

    val connectionState: StateFlow<ConnectionState> = pumpDriver.observeConnectionState()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), ConnectionState.DISCONNECTED)

    val cgm: StateFlow<CgmReading?> = repository.observeLatestCgm()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    val iob: StateFlow<IoBReading?> = repository.observeLatestIoB()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    val basalRate: StateFlow<BasalReading?> = repository.observeLatestBasal()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    val battery: StateFlow<BatteryStatus?> = repository.observeLatestBattery()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    val reservoir: StateFlow<ReservoirReading?> = repository.observeLatestReservoir()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    val syncStatus: StateFlow<SyncStatus> = backendSyncManager.syncStatus

    /** Dynamic glucose thresholds from backend settings (reactive). */
    private val _glucoseThresholds = MutableStateFlow(thresholdsFromStore())
    val glucoseThresholds: StateFlow<GlucoseThresholds> = _glucoseThresholds.asStateFlow()

    init {
        // Refresh glucose range from backend on screen load if stale (15 min)
        if (glucoseRangeStore.isStale(maxAgeMs = RANGE_REFRESH_INTERVAL_MS)) {
            viewModelScope.launch { refreshGlucoseRange() }
        }
        // Refresh safety limits from backend if stale (1 hour)
        if (safetyLimitsStore.isStale()) {
            viewModelScope.launch { authRepository.refreshSafetyLimits() }
        }
    }

    private val _isRefreshing = MutableStateFlow(false)
    val isRefreshing: StateFlow<Boolean> = _isRefreshing.asStateFlow()

    // -- Glucose trend chart state --------------------------------------------

    private val _selectedPeriod = MutableStateFlow(ChartPeriod.THREE_HOURS)
    val selectedPeriod: StateFlow<ChartPeriod> = _selectedPeriod.asStateFlow()

    val cgmHistory: StateFlow<List<CgmReading>> = _selectedPeriod
        .flatMapLatest { period ->
            val since = Instant.ofEpochMilli(
                System.currentTimeMillis() - period.hours * 3600_000L,
            )
            repository.observeCgmHistory(since)
        }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val iobHistory: StateFlow<List<IoBReading>> = _selectedPeriod
        .flatMapLatest { period ->
            val since = Instant.ofEpochMilli(
                System.currentTimeMillis() - period.hours * 3600_000L,
            )
            repository.observeIoBHistory(since)
        }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val basalHistory: StateFlow<List<BasalReading>> = _selectedPeriod
        .flatMapLatest { period ->
            val since = Instant.ofEpochMilli(
                System.currentTimeMillis() - period.hours * 3600_000L,
            )
            repository.observeBasalHistory(since)
        }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val bolusHistory: StateFlow<List<BolusEvent>> = _selectedPeriod
        .flatMapLatest { period ->
            val since = Instant.ofEpochMilli(
                System.currentTimeMillis() - period.hours * 3600_000L,
            )
            repository.observeBolusHistory(since)
        }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    fun onPeriodSelected(period: ChartPeriod) {
        _selectedPeriod.value = period
    }

    // -- Time in Range state --------------------------------------------------

    private val _selectedTirPeriod = MutableStateFlow(TirPeriod.TWENTY_FOUR_HOURS)
    val selectedTirPeriod: StateFlow<TirPeriod> = _selectedTirPeriod.asStateFlow()

    val timeInRange: StateFlow<TimeInRangeData?> = combine(
        _selectedTirPeriod,
        _glucoseThresholds,
    ) { period, thresholds -> Pair(period, thresholds) }
        .flatMapLatest { (period, thresholds) ->
            val since = Instant.ofEpochMilli(
                System.currentTimeMillis() - period.hours * 3600_000L,
            )
            repository.observeTimeInRange(since, thresholds.low, thresholds.high)
        }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    fun onTirPeriodSelected(period: TirPeriod) {
        _selectedTirPeriod.value = period
    }

    /**
     * Manually trigger a pump data refresh. Reads are staggered sequentially
     * to avoid overwhelming the pump with simultaneous BLE requests (same
     * discipline as PumpPollingOrchestrator).
     */
    fun refreshData() {
        if (!_isRefreshing.compareAndSet(expect = false, update = true)) return
        viewModelScope.launch {
            try {
                // Refresh glucose range concurrently -- don't block BLE reads
                launch { refreshGlucoseRange() }

                pumpDriver.getIoB().onSuccess { repository.saveIoB(it) }
                delay(PumpPollingOrchestrator.REQUEST_STAGGER_MS)
                pumpDriver.getBasalRate().onSuccess { repository.saveBasal(it) }
                delay(PumpPollingOrchestrator.REQUEST_STAGGER_MS)
                pumpDriver.getBatteryStatus().onSuccess { repository.saveBattery(it) }
                delay(PumpPollingOrchestrator.REQUEST_STAGGER_MS)
                pumpDriver.getReservoirLevel().onSuccess { repository.saveReservoir(it) }
                delay(PumpPollingOrchestrator.REQUEST_STAGGER_MS)
                pumpDriver.getCgmStatus().onSuccess { repository.saveCgm(it) }
            } catch (e: Exception) {
                Timber.w(e, "Error during manual data refresh")
            } finally {
                _isRefreshing.value = false
            }
        }
    }

    private fun thresholdsFromStore(): GlucoseThresholds = GlucoseThresholds(
        urgentLow = glucoseRangeStore.urgentLow,
        low = glucoseRangeStore.low,
        high = glucoseRangeStore.high,
        urgentHigh = glucoseRangeStore.urgentHigh,
    )

    private suspend fun refreshGlucoseRange() {
        try {
            val response = api.getGlucoseRange()
            if (response.isSuccessful) {
                response.body()?.let { range ->
                    val urgentLow = range.urgentLow.toInt().coerceIn(MIN_THRESHOLD, MAX_THRESHOLD)
                    val low = range.lowTarget.toInt().coerceIn(MIN_THRESHOLD, MAX_THRESHOLD)
                    val high = range.highTarget.toInt().coerceIn(MIN_THRESHOLD, MAX_THRESHOLD)
                    val urgentHigh = range.urgentHigh.toInt().coerceIn(MIN_THRESHOLD, MAX_THRESHOLD)
                    if (low >= high) {
                        Timber.w("Invalid glucose range: low=%d >= high=%d, skipping update", low, high)
                        return
                    }
                    glucoseRangeStore.updateAll(
                        urgentLow = urgentLow,
                        low = low,
                        high = high,
                        urgentHigh = urgentHigh,
                    )
                    val newThresholds = thresholdsFromStore()
                    if (newThresholds != _glucoseThresholds.value) {
                        _glucoseThresholds.value = newThresholds
                        Timber.d("Glucose range updated: %s", newThresholds)
                    }
                }
            } else {
                Timber.w("Glucose range refresh failed: HTTP %d", response.code())
            }
        } catch (e: Exception) {
            Timber.w(e, "Failed to refresh glucose range")
        }
    }

    companion object {
        internal const val RANGE_REFRESH_INTERVAL_MS = 900_000L
        private const val MIN_THRESHOLD = 20
        private const val MAX_THRESHOLD = 500
    }
}
