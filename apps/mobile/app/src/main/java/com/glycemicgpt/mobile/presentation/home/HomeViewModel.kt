package com.glycemicgpt.mobile.presentation.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.glycemicgpt.mobile.data.local.AnalyticsSettingsStore
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.local.GlucoseRangeStore
import com.glycemicgpt.mobile.data.local.PumpProfileStore
import com.glycemicgpt.mobile.data.local.SafetyLimitsStore
import com.glycemicgpt.mobile.data.remote.GlycemicGptApi
import com.glycemicgpt.mobile.data.remote.dto.PluginDeclarationRequest
import com.glycemicgpt.mobile.data.repository.AuthRepository
import com.glycemicgpt.mobile.data.repository.PumpDataRepository
import com.glycemicgpt.mobile.domain.compute.DashboardComputations
import com.glycemicgpt.mobile.domain.model.AgpProfile
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BatteryStatus
import com.glycemicgpt.mobile.domain.model.BolusCategory
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmStats
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.model.EnrichedBolusEvent
import com.glycemicgpt.mobile.domain.model.InsulinSummary
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.plugin.DevicePlugin
import com.glycemicgpt.mobile.domain.plugin.asBolusCategoryProvider
import com.glycemicgpt.mobile.domain.model.ReservoirReading
import com.glycemicgpt.mobile.domain.model.TimeInRangeData
import com.glycemicgpt.mobile.domain.plugin.ui.DashboardCardDescriptor
import com.glycemicgpt.mobile.domain.pump.PumpDriver
import com.glycemicgpt.mobile.plugin.PluginRegistry
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
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.distinctUntilChangedBy
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import timber.log.Timber
import java.time.Instant
import java.time.ZoneId
import javax.inject.Inject

/** A dashboard card paired with the plugin that produced it. */
data class PluginCard(val pluginId: String, val card: DashboardCardDescriptor)

@OptIn(ExperimentalCoroutinesApi::class)
@HiltViewModel
class HomeViewModel @Inject constructor(
    private val pumpDriver: PumpDriver,
    private val repository: PumpDataRepository,
    private val backendSyncManager: BackendSyncManager,
    private val glucoseRangeStore: GlucoseRangeStore,
    private val safetyLimitsStore: SafetyLimitsStore,
    private val analyticsSettingsStore: AnalyticsSettingsStore,
    private val pumpProfileStore: PumpProfileStore,
    private val appSettingsStore: AppSettingsStore,
    private val authRepository: AuthRepository,
    private val api: GlycemicGptApi,
    private val pluginRegistry: PluginRegistry,
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

    /** Dashboard cards contributed by active plugins, paired with their plugin ID. */
    val pluginCards: StateFlow<List<PluginCard>> =
        pluginRegistry.allActivePlugins.flatMapLatest { plugins ->
            if (plugins.isEmpty()) {
                flowOf(emptyList())
            } else {
                combine(plugins.map { plugin ->
                    plugin.observeDashboardCards().map { cards ->
                        cards.map { card -> PluginCard(plugin.metadata.id, card) }
                    }
                }) { arrays ->
                    arrays.flatMap { it.toList() }.sortedBy { it.card.priority }
                }
            }
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    /** Dynamic glucose thresholds from backend settings (reactive). */
    private val _glucoseThresholds = MutableStateFlow(thresholdsFromStore())
    val glucoseThresholds: StateFlow<GlucoseThresholds> = _glucoseThresholds.asStateFlow()

    /** Day boundary hour for aligning analytics periods with pump Delivery Summary. */
    private val _dayBoundaryHour = MutableStateFlow(analyticsSettingsStore.dayBoundaryHour)
    val dayBoundaryHour: StateFlow<Int> = _dayBoundaryHour.asStateFlow()

    /** Custom display labels for bolus categories, synced from backend. */
    private val _categoryLabels = MutableStateFlow(analyticsSettingsStore.categoryLabels)
    val categoryLabels: StateFlow<Map<String, String>> = _categoryLabels.asStateFlow()

    /**
     * Reverse map from platform BolusCategory -> pump-native label, built from
     * the active plugin's BolusCategoryProvider. Null when no plugin is active
     * or the provider doesn't declare categories. Only consumed when the debug
     * "Show Pump Labels" toggle is enabled.
     */
    val pumpLabelMap: StateFlow<Map<BolusCategory, String>?> =
        pluginRegistry.activePumpPlugin.map { plugin ->
            val provider = plugin?.asBolusCategoryProvider() ?: return@map null
            try {
                val declared = provider.declaredCategories()
                if (declared.isEmpty()) return@map null
                buildMap {
                    for (pumpCat in declared) {
                        val platformName = provider.toPlatformCategory(pumpCat) ?: continue
                        val category = BolusCategory.fromName(platformName)
                        put(category, pumpCat)
                    }
                }.ifEmpty { null }
            } catch (e: Exception) {
                Timber.w(e, "Failed to build pump label map from plugin")
                null
            }
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    /** Debug-only: whether to show pump-native labels next to display labels. */
    val showPumpLabels: Boolean
        get() = appSettingsStore.showPumpLabels

    init {
        // Refresh glucose range from backend on screen load if stale (15 min)
        if (glucoseRangeStore.isStale(maxAgeMs = RANGE_REFRESH_INTERVAL_MS)) {
            viewModelScope.launch { refreshGlucoseRange() }
        }
        // Refresh safety limits from backend if stale (1 hour)
        if (safetyLimitsStore.isStale()) {
            viewModelScope.launch {
                authRepository.refreshSafetyLimits()
                pluginRegistry.refreshSafetyLimits()
            }
        }
        // Refresh analytics config from backend if stale (15 min)
        if (analyticsSettingsStore.isStale()) {
            viewModelScope.launch { refreshAnalyticsConfig() }
        }
        // Refresh pump profile from backend if stale (1 hour)
        if (pumpProfileStore.isStale()) {
            viewModelScope.launch { refreshPumpProfile() }
        }
        // Sync plugin declarations to backend when active pump plugin changes
        viewModelScope.launch {
            pluginRegistry.activePumpPlugin
                .distinctUntilChangedBy { it?.metadata?.id }
                .collect { plugin ->
                    syncPluginDeclaration(plugin)
                }
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

    // -- AGP Chart state ------------------------------------------------------

    private val _selectedAgpPeriod = MutableStateFlow(AgpPeriod.FOURTEEN_DAYS)
    val selectedAgpPeriod: StateFlow<AgpPeriod> = _selectedAgpPeriod.asStateFlow()

    val agpProfile: StateFlow<AgpProfile?> = _selectedAgpPeriod
        .flatMapLatest { period ->
            val since = Instant.ofEpochMilli(
                System.currentTimeMillis() - period.days * 24 * 3600_000L,
            )
            repository.observeCgmHistoryAll(since).map { readings ->
                DashboardComputations.computeAgp(readings, period.days)
            }
        }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    fun onAgpPeriodSelected(period: AgpPeriod) {
        _selectedAgpPeriod.value = period
    }

    // -- CGM Stats state ------------------------------------------------------

    private val _selectedCgmStatsPeriod = MutableStateFlow(TirPeriod.TWENTY_FOUR_HOURS)
    val selectedCgmStatsPeriod: StateFlow<TirPeriod> = _selectedCgmStatsPeriod.asStateFlow()

    val cgmStats: StateFlow<CgmStats?> = _selectedCgmStatsPeriod
        .flatMapLatest { period ->
            val since = Instant.ofEpochMilli(
                System.currentTimeMillis() - period.hours * 3600_000L,
            )
            repository.observeCgmHistoryAll(since).map { readings ->
                DashboardComputations.computeCgmStats(readings)
            }
        }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    fun onCgmStatsPeriodSelected(period: TirPeriod) {
        _selectedCgmStatsPeriod.value = period
    }

    // -- Insulin Summary state ------------------------------------------------

    private val _selectedInsulinPeriod = MutableStateFlow(TirPeriod.TWENTY_FOUR_HOURS)
    val selectedInsulinPeriod: StateFlow<TirPeriod> = _selectedInsulinPeriod.asStateFlow()

    val insulinSummary: StateFlow<InsulinSummary?> = combine(
        _selectedInsulinPeriod,
        _dayBoundaryHour,
        pluginRegistry.activePumpPlugin,
    ) { period, boundary, plugin -> Triple(period, boundary, plugin) }
        .flatMapLatest { (period, boundary, plugin) ->
            val since = DashboardComputations.periodStart(
                period.daysBack, boundary, ZoneId.systemDefault(),
            )
            val categoryProvider = plugin?.asBolusCategoryProvider()
            combine(
                repository.observeBasalHistoryAll(since),
                repository.observeBolusHistoryAll(since),
            ) { basals, boluses ->
                DashboardComputations.computeInsulinSummary(
                    basals, boluses, period.hours, categoryProvider,
                )
            }
        }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    fun onInsulinPeriodSelected(period: TirPeriod) {
        _selectedInsulinPeriod.value = period
    }

    // -- Enriched Boluses state -----------------------------------------------

    private val _selectedBolusPeriod = MutableStateFlow(TirPeriod.TWENTY_FOUR_HOURS)
    val selectedBolusPeriod: StateFlow<TirPeriod> = _selectedBolusPeriod.asStateFlow()

    val enrichedBoluses: StateFlow<List<EnrichedBolusEvent>> = combine(
        _selectedBolusPeriod,
        _dayBoundaryHour,
    ) { period, boundary -> Pair(period, boundary) }
        .flatMapLatest { (period, boundary) ->
            val since = DashboardComputations.periodStart(
                period.daysBack, boundary, ZoneId.systemDefault(),
            )
            combine(
                repository.observeBolusHistoryAll(since),
                repository.observeCgmHistoryAll(since),
                repository.observeIoBHistoryAll(since),
            ) { boluses, cgmReadings, iobReadings ->
                DashboardComputations.enrichBoluses(boluses, cgmReadings, iobReadings)
            }
        }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    fun onBolusPeriodSelected(period: TirPeriod) {
        _selectedBolusPeriod.value = period
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
                // Refresh settings concurrently -- don't block BLE reads
                launch { refreshGlucoseRange() }
                launch { refreshAnalyticsConfig() }
                launch { refreshPumpProfile() }
                // If backend call fails, refreshSafetyLimits re-reads the store's
                // last-known-good values -- harmless no-op, plugins keep safe limits.
                launch {
                    authRepository.refreshSafetyLimits()
                    pluginRegistry.refreshSafetyLimits()
                }

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

    private suspend fun refreshAnalyticsConfig() {
        try {
            val response = api.getAnalyticsConfig()
            if (response.isSuccessful) {
                response.body()?.let { config ->
                    val hour = config.dayBoundaryHour.coerceIn(0, 23)
                    // Prefer displayLabels (new format) over categoryLabels (legacy)
                    val resolvedLabels = AnalyticsSettingsStore.displayLabelsToMap(
                        config.displayLabels,
                        config.categoryLabels,
                    )
                    analyticsSettingsStore.updateAll(hour, resolvedLabels)
                    if (hour != _dayBoundaryHour.value) {
                        _dayBoundaryHour.value = hour
                        Timber.d("Analytics day boundary updated: %d", hour)
                    }
                    val labels = resolvedLabels ?: emptyMap()
                    if (labels != _categoryLabels.value) {
                        _categoryLabels.value = labels
                        Timber.d("Category labels updated: %s", labels.keys)
                    }
                }
            } else {
                Timber.w("Analytics config refresh failed: HTTP %d", response.code())
            }
        } catch (e: Exception) {
            Timber.w(e, "Failed to refresh analytics config")
        }
    }

    private suspend fun refreshPumpProfile() {
        try {
            val response = api.getPumpProfile()
            if (response.isSuccessful) {
                response.body()?.let { profile ->
                    pumpProfileStore.updateAll(
                        profileName = profile.profileName,
                        diaMinutes = profile.diaMinutes ?: 0,
                        maxBolusUnits = profile.maxBolusUnits ?: 0f,
                        segmentCount = profile.segments.size,
                    )
                    Timber.d("Pump profile updated: %s (%d segments)",
                        profile.profileName, profile.segments.size)
                }
            } else if (response.code() != 404) {
                // 404 is expected when no profile is synced yet
                Timber.w("Pump profile refresh failed: HTTP %d", response.code())
            }
        } catch (e: Exception) {
            Timber.w(e, "Failed to refresh pump profile")
        }
    }

    private suspend fun syncPluginDeclaration(plugin: DevicePlugin?) {
        try {
            if (plugin == null) {
                val response = api.deletePluginDeclarations()
                if (response.isSuccessful || response.code() == 404) {
                    Timber.d("Plugin declaration cleared")
                } else {
                    Timber.w("Failed to delete plugin declaration: HTTP %d", response.code())
                }
                return
            }
            val provider = plugin.asBolusCategoryProvider()
            if (provider == null) {
                val resp = api.deletePluginDeclarations()
                if (resp.isSuccessful || resp.code() == 404) {
                    Timber.d("Plugin declaration cleared (no bolus category provider)")
                }
                return
            }
            val declared = provider.declaredCategories()
            if (declared.isEmpty()) {
                val resp = api.deletePluginDeclarations()
                if (resp.isSuccessful || resp.code() == 404) {
                    Timber.d("Plugin declaration cleared (empty declared categories)")
                }
                return
            }
            val mappings = buildMap {
                for (pumpCat in declared) {
                    val platform = provider.toPlatformCategory(pumpCat) ?: continue
                    put(pumpCat, platform)
                }
            }
            val request = PluginDeclarationRequest(
                pluginId = plugin.metadata.id,
                pluginName = plugin.metadata.name,
                pluginVersion = plugin.metadata.version,
                declaredCategories = declared.toList(),
                categoryMappings = mappings,
            )
            val response = api.putPluginDeclarations(request)
            if (response.isSuccessful) {
                Timber.d("Plugin declaration synced: %s", plugin.metadata.id)
            } else {
                Timber.w("Failed to sync plugin declaration: HTTP %d", response.code())
            }
        } catch (e: Exception) {
            Timber.w(e, "Failed to sync plugin declaration")
        }
    }

    companion object {
        internal const val RANGE_REFRESH_INTERVAL_MS = 900_000L
        private const val MIN_THRESHOLD = 20
        private const val MAX_THRESHOLD = 500
    }
}
