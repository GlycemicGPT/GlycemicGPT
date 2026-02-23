package com.glycemicgpt.mobile.service

import com.glycemicgpt.mobile.data.local.GlucoseRangeStore
import com.glycemicgpt.mobile.data.local.dao.RawHistoryLogDao
import com.glycemicgpt.mobile.data.local.entity.RawHistoryLogEntity
import com.glycemicgpt.mobile.data.repository.PumpDataRepository
import com.glycemicgpt.mobile.data.repository.SyncQueueEnqueuer
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.pump.HistoryLogParser
import com.glycemicgpt.mobile.domain.pump.PumpDriver
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import com.glycemicgpt.mobile.wear.WearDataSender
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import timber.log.Timber
import java.time.Instant
import java.time.temporal.ChronoUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Orchestrates periodic polling of pump data and persists results to Room.
 *
 * Poll intervals:
 * - IoB + basal rate + CGM: every 15 seconds (keep-alive; pump drops idle connections at ~30s)
 * - Bolus history: every 5 minutes (AC2)
 * - Battery + reservoir: every 5 minutes (AC3)
 *
 * Polling pauses when BLE connection is lost and resumes on reconnect (AC7).
 * Reduces frequency when phone battery is low (AC8).
 */
@Singleton
class PumpPollingOrchestrator @Inject constructor(
    private val pumpDriver: PumpDriver,
    private val repository: PumpDataRepository,
    private val syncEnqueuer: SyncQueueEnqueuer,
    private val rawHistoryLogDao: RawHistoryLogDao,
    private val wearDataSender: WearDataSender,
    private val glucoseRangeStore: GlucoseRangeStore,
    private val historyLogParser: HistoryLogParser,
) {

    /** Set by PumpConnectionService to trigger immediate sync after enqueue. */
    @Volatile
    var backendSyncManager: BackendSyncManager? = null

    /** Track the last known raw event sequence number to fetch incrementally. */
    @Volatile
    private var lastSequenceNumber: Int = 0

    /** Whether hardware info has been cached this session. */
    @Volatile
    private var hardwareInfoCached: Boolean = false

    /** Whether we have been connected at least once this service session.
     *  Used to distinguish reconnection (accelerated polling) from initial connection. */
    @Volatile
    private var hasBeenConnectedBefore: Boolean = false

    /** Track the last alert type sent to watch to avoid re-sending the same alert. */
    @Volatile
    private var previousAlertType: String? = null

    private val lock = Any()
    private var fastJob: Job? = null
    private var mediumJob: Job? = null
    private var slowJob: Job? = null
    private var connectionWatcherJob: Job? = null

    @Volatile
    var phoneBatteryLow: Boolean = false

    /**
     * Start watching connection state and polling when connected.
     * Call this from the foreground service's onCreate.
     */
    fun start(scope: CoroutineScope) {
        stop() // cancel any previous jobs
        synchronized(lock) {
            connectionWatcherJob = scope.launch {
                // Restore last known sequence number from Room to avoid re-downloading
                lastSequenceNumber = rawHistoryLogDao.getMaxSequenceNumber() ?: 0

                pumpDriver.observeConnectionState().collectLatest { state ->
                    if (state == ConnectionState.CONNECTED) {
                        val isReconnection = hasBeenConnectedBefore
                        hasBeenConnectedBefore = true
                        if (isReconnection) {
                            Timber.d("Pump reconnected, starting accelerated polling (reduced initial delays)")
                            startReconnectionPollingLoops(scope)
                        } else {
                            Timber.d("Pump connected (initial), starting normal polling")
                            startPollingLoops(scope)
                        }
                    } else {
                        Timber.d("Pump disconnected (state=%s), pausing polling", state)
                        previousAlertType = null
                        cancelPollingLoops()
                    }
                }
            }
        }
    }

    /** Stop all polling. Call from service onDestroy. */
    fun stop() {
        synchronized(lock) {
            cancelPollingLoops()
            connectionWatcherJob?.cancel()
            connectionWatcherJob = null
            hasBeenConnectedBefore = false
        }
    }

    private fun startPollingLoops(scope: CoroutineScope) {
        synchronized(lock) {
            cancelPollingLoops()

            fastJob = scope.launch { pollFastLoop() }
            mediumJob = scope.launch { pollMediumLoop() }
            slowJob = scope.launch { pollSlowLoop() }
        }
    }

    /**
     * Start polling with reduced initial delays for reconnection.
     * Bolus history fires within 5s instead of 60s to backfill missed data.
     * Battery/reservoir/history fires within 3s instead of 30s.
     */
    private fun startReconnectionPollingLoops(scope: CoroutineScope) {
        synchronized(lock) {
            cancelPollingLoops()

            fastJob = scope.launch { pollFastLoop(INITIAL_POLL_DELAY_MS) }
            mediumJob = scope.launch { pollMediumLoop(RECONNECT_MEDIUM_DELAY_MS) }
            slowJob = scope.launch { pollSlowLoop(RECONNECT_SLOW_DELAY_MS) }
        }
    }

    private fun cancelPollingLoops() {
        synchronized(lock) {
            fastJob?.cancel()
            mediumJob?.cancel()
            slowJob?.cancel()
            fastJob = null
            mediumJob = null
            slowJob = null
        }
    }

    private fun effectiveInterval(baseMs: Long): Long =
        if (phoneBatteryLow) baseMs * LOW_BATTERY_MULTIPLIER else baseMs

    /**
     * Fast loop: IoB + basal rate + CGM at least every ~15s.
     *
     * Waits [initialDelayMs] for the connection to stabilize, then
     * staggers requests by [REQUEST_STAGGER_MS] to avoid overwhelming the
     * pump with simultaneous BLE writes. The actual period is approximately
     * INTERVAL_FAST_MS + (FAST_REQUEST_COUNT - 1) * REQUEST_STAGGER_MS
     * plus any BLE response latency.
     */
    private suspend fun pollFastLoop(initialDelayMs: Long = INITIAL_POLL_DELAY_MS) {
        delay(initialDelayMs)
        while (true) {
            pollIoB()
            delay(REQUEST_STAGGER_MS)
            pollBasal()
            delay(REQUEST_STAGGER_MS)
            pollCgm()
            delay(effectiveInterval(INTERVAL_FAST_MS))
        }
    }

    /** Medium loop: last bolus status at least every ~5 min. */
    private suspend fun pollMediumLoop(initialDelayMs: Long = MEDIUM_LOOP_INITIAL_DELAY_MS) {
        delay(initialDelayMs)
        while (true) {
            pollBolusHistory()
            delay(effectiveInterval(INTERVAL_MEDIUM_MS))
        }
    }

    /** Slow loop: battery + reservoir + raw history logs at least every ~5 min. */
    private suspend fun pollSlowLoop(initialDelayMs: Long = SLOW_LOOP_INITIAL_DELAY_MS) {
        delay(initialDelayMs)
        while (true) {
            pollBattery()
            delay(REQUEST_STAGGER_MS)
            pollReservoir()
            delay(REQUEST_STAGGER_MS)
            pollHistoryLogs()
            delay(REQUEST_STAGGER_MS)
            cacheHardwareInfoOnce()
            delay(effectiveInterval(INTERVAL_SLOW_MS))
        }
    }

    private suspend fun pollIoB() {
        pumpDriver.getIoB()
            .onSuccess {
                repository.saveIoB(it)
                syncEnqueuer.enqueueIoB(it)
                backendSyncManager?.triggerSync()
                try {
                    wearDataSender.sendIoB(it.iob, it.timestamp.toEpochMilli())
                } catch (e: Exception) {
                    Timber.w(e, "Failed to send IoB to watch")
                }
            }
            .onFailure { Timber.w(it, "Failed to poll IoB") }
    }

    private suspend fun pollBasal() {
        pumpDriver.getBasalRate()
            .onSuccess {
                repository.saveBasal(it)
                syncEnqueuer.enqueueBasal(it)
                backendSyncManager?.triggerSync()
            }
            .onFailure { Timber.w(it, "Failed to poll basal rate") }
    }

    private suspend fun pollBolusHistory() {
        val since = repository.getLatestBolusTimestamp()
            ?: Instant.now().minus(7, ChronoUnit.DAYS)
        pumpDriver.getBolusHistory(since)
            .onSuccess { events ->
                if (events.isNotEmpty()) {
                    repository.saveBoluses(events)
                    syncEnqueuer.enqueueBoluses(events)
                    backendSyncManager?.triggerSync()
                    Timber.d("Saved %d new bolus events", events.size)
                }
            }
            .onFailure { Timber.w(it, "Failed to poll bolus history") }
    }

    private suspend fun pollCgm() {
        try {
            pumpDriver.getCgmStatus()
                .onSuccess {
                    repository.saveCgm(it)
                    try {
                        wearDataSender.sendCgm(
                            mgDl = it.glucoseMgDl,
                            trend = it.trendArrow.name,
                            timestampMs = it.timestamp.toEpochMilli(),
                            low = glucoseRangeStore.low,
                            high = glucoseRangeStore.high,
                            urgentLow = glucoseRangeStore.urgentLow,
                            urgentHigh = glucoseRangeStore.urgentHigh,
                        )
                    } catch (e: Exception) {
                        Timber.w(e, "Failed to send CGM to watch")
                    }

                    // Alert threshold detection for watch (uses dynamic thresholds)
                    val alertType = detectAlertForCgm(it.glucoseMgDl)
                    try {
                        if (alertType != null && alertType != previousAlertType) {
                            wearDataSender.sendAlert(
                                type = alertType,
                                bgValue = it.glucoseMgDl,
                                timestampMs = it.timestamp.toEpochMilli(),
                                message = "${alertLabel(alertType)} ${it.glucoseMgDl} mg/dL",
                            )
                            previousAlertType = alertType
                        } else if (alertType == null && previousAlertType != null) {
                            wearDataSender.clearAlert()
                            previousAlertType = null
                        }
                    } catch (e: Exception) {
                        Timber.w(e, "Failed to send alert to watch")
                    }
                }
                .onFailure { Timber.w(it, "Failed to poll CGM status") }
        } catch (e: Exception) {
            Timber.w(e, "CGM poll exception")
        }
    }

    companion object {
        /** Default safety limits for data validity (sensor range 20-500 mg/dL). */
        private val DATA_VALIDITY_LIMITS = SafetyLimits()

        const val INTERVAL_FAST_MS = 15_000L       // IoB + basal + CGM (keep-alive: pump drops idle connections at ~30s)
        const val INTERVAL_MEDIUM_MS = 300_000L     // bolus history (5 min)
        const val INTERVAL_SLOW_MS = 300_000L       // battery + reservoir (5 min)

        /** Delay before first poll after connection to let the pump settle.
         *  Keep short to avoid idle-timeout disconnects (pump drops idle at ~3-5s). */
        const val INITIAL_POLL_DELAY_MS = 500L

        /** Stagger between consecutive BLE requests within a loop iteration.
         *  500ms gives the pump time to process each request and respond before
         *  the next write arrives. Lower values (200ms) can cause GATT_ERROR. */
        const val REQUEST_STAGGER_MS = 500L

        /** Wait before starting the medium loop (last bolus status).
         *  Let the fast loop run several cycles to establish a stable
         *  connection rhythm before introducing additional request types. */
        const val MEDIUM_LOOP_INITIAL_DELAY_MS = 60_000L  // 60 seconds

        /** Wait before starting the slow loop (battery, reservoir, history).
         *  Gives the fast loop a couple of cycles to stabilize BLE before
         *  introducing additional lightweight status reads. */
        const val SLOW_LOOP_INITIAL_DELAY_MS = 30_000L    // 30 seconds

        /** Delay before starting medium loop on reconnection (bolus history).
         *  Short delay to let the fast loop establish rhythm first, but much
         *  faster than the initial 60s delay for immediate bolus backfill. */
        const val RECONNECT_MEDIUM_DELAY_MS = 5_000L      // 5 seconds

        /** Delay before starting slow loop on reconnection (battery, reservoir).
         *  Let fast loop fire first, then quickly catch up on hardware status. */
        const val RECONNECT_SLOW_DELAY_MS = 3_000L        // 3 seconds

        // When phone battery is low, slow everything down by this factor
        const val LOW_BATTERY_MULTIPLIER = 3

        fun alertLabel(type: String): String = when (type) {
            "urgent_low" -> "URGENT LOW"
            "urgent_high" -> "URGENT HIGH"
            "low" -> "LOW"
            "high" -> "HIGH"
            else -> ""
        }
    }

    /** Detect alert type using dynamically configured glucose thresholds. */
    private fun detectAlertForCgm(mgDl: Int): String? = when {
        mgDl <= glucoseRangeStore.urgentLow -> "urgent_low"
        mgDl >= glucoseRangeStore.urgentHigh -> "urgent_high"
        mgDl <= glucoseRangeStore.low -> "low"
        mgDl >= glucoseRangeStore.high -> "high"
        else -> null
    }

    private suspend fun pollBattery() {
        pumpDriver.getBatteryStatus()
            .onSuccess {
                repository.saveBattery(it)
                syncEnqueuer.enqueueBattery(it)
                backendSyncManager?.triggerSync()
            }
            .onFailure { Timber.w(it, "Failed to poll battery") }
    }

    private suspend fun pollReservoir() {
        pumpDriver.getReservoirLevel()
            .onSuccess {
                repository.saveReservoir(it)
                syncEnqueuer.enqueueReservoir(it)
                backendSyncManager?.triggerSync()
            }
            .onFailure { Timber.w(it, "Failed to poll reservoir") }
    }

    private suspend fun pollHistoryLogs() {
        pumpDriver.getHistoryLogs(sinceSequence = lastSequenceNumber)
            .onSuccess { records ->
                if (records.isNotEmpty()) {
                    val entities = records.map { record ->
                        RawHistoryLogEntity(
                            sequenceNumber = record.sequenceNumber,
                            rawBytesB64 = record.rawBytesB64,
                            eventTypeId = record.eventTypeId,
                            pumpTimeSeconds = record.pumpTimeSeconds,
                        )
                    }
                    rawHistoryLogDao.insertAll(entities)
                    lastSequenceNumber = records.maxOf { it.sequenceNumber }
                    backendSyncManager?.triggerSync()
                    Timber.d("Saved %d raw history log records", records.size)

                    // Use default SafetyLimits for data validity (sensor range 20-500 mg/dL).
                    // Do NOT use alert thresholds (urgentLow/urgentHigh) here -- those are
                    // user alert preferences (e.g., urgentHigh=250), not sensor validity
                    // bounds. Using them would silently drop real readings above 250 mg/dL.
                    val limits = DATA_VALIDITY_LIMITS

                    // Extract CGM readings from history logs to fill chart gaps
                    val cgmReadings = historyLogParser.extractCgmFromHistoryLogs(records, limits)
                    if (cgmReadings.isNotEmpty()) {
                        repository.saveCgmBatch(cgmReadings)
                        Timber.d("Backfilled %d CGM readings from history logs", cgmReadings.size)
                    }

                    // Extract bolus events from history logs
                    val bolusEvents = historyLogParser.extractBolusesFromHistoryLogs(records, limits)
                    if (bolusEvents.isNotEmpty()) {
                        repository.saveBoluses(bolusEvents)
                        syncEnqueuer.enqueueBoluses(bolusEvents)
                        Timber.d("Backfilled %d bolus events from history logs", bolusEvents.size)
                    }

                    // Extract basal delivery events from history logs
                    val basalReadings = historyLogParser.extractBasalFromHistoryLogs(records, limits)
                    if (basalReadings.isNotEmpty()) {
                        repository.saveBasalBatch(basalReadings)
                        syncEnqueuer.enqueueBasalBatch(basalReadings)
                        backendSyncManager?.triggerSync()
                        Timber.d("Backfilled %d basal readings from history logs", basalReadings.size)
                    }
                }
            }
            .onFailure { Timber.w(it, "Failed to poll history logs") }
    }

    private suspend fun cacheHardwareInfoOnce() {
        if (hardwareInfoCached) return
        pumpDriver.getPumpHardwareInfo()
            .onSuccess { info ->
                backendSyncManager?.cachedHardwareInfo = info
                hardwareInfoCached = true
                Timber.d("Cached pump hardware info: serial=%d", info.serialNumber)
            }
            .onFailure { Timber.w(it, "Failed to get pump hardware info") }
    }
}
