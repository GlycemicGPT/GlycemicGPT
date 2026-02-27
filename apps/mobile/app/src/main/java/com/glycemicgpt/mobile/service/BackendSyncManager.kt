package com.glycemicgpt.mobile.service

import kotlinx.coroutines.ExperimentalCoroutinesApi
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.local.AuthTokenStore
import com.glycemicgpt.mobile.data.local.dao.RawHistoryLogDao
import com.glycemicgpt.mobile.data.local.dao.SyncDao
import com.glycemicgpt.mobile.data.remote.GlycemicGptApi
import com.glycemicgpt.mobile.data.remote.dto.PumpEventDto
import com.glycemicgpt.mobile.data.remote.dto.PumpHardwareInfoDto
import com.glycemicgpt.mobile.data.remote.dto.PumpPushRequest
import com.glycemicgpt.mobile.data.remote.dto.PumpRawEventDto
import com.glycemicgpt.mobile.domain.model.PumpHardwareInfo
import com.squareup.moshi.Moshi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.selects.onTimeout
import kotlinx.coroutines.selects.select
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

data class SyncStatus(
    val lastSyncAtMs: Long = 0L,
    val pendingCount: Int = 0,
    val lastError: String? = null,
)

/**
 * Coroutine-based queue processor that pushes local pump events to the backend.
 *
 * Checks for pending items every [POLL_INTERVAL_MS] and can be triggered
 * immediately via [triggerSync].
 */
@OptIn(ExperimentalCoroutinesApi::class)
@Singleton
class BackendSyncManager @Inject constructor(
    private val syncDao: SyncDao,
    private val rawHistoryLogDao: RawHistoryLogDao,
    private val api: GlycemicGptApi,
    private val authTokenStore: AuthTokenStore,
    private val appSettingsStore: AppSettingsStore,
    private val moshi: Moshi,
) {

    companion object {
        const val POLL_INTERVAL_MS = 3_000L
        const val BATCH_SIZE = 50
        const val RAW_BATCH_SIZE = 100
        const val MAX_RETRIES = 5
        const val MAX_QUEUE_SIZE = 5000
        private const val STALE_SENDING_TIMEOUT_MS = 60_000L // 1 minute
        private const val CLEANUP_INTERVAL_MS = 3_600_000L // 1 hour
    }

    /** Cached pump hardware info, set by PumpPollingOrchestrator on first connect. */
    @Volatile
    var cachedHardwareInfo: PumpHardwareInfo? = null

    private val _syncStatus = MutableStateFlow(SyncStatus())
    val syncStatus: StateFlow<SyncStatus> = _syncStatus.asStateFlow()

    private var syncLoopJob: Job? = null
    private var pendingCountJob: Job? = null

    private val triggerChannel = Channel<Unit>(Channel.CONFLATED)
    @Volatile
    private var lastCleanupMs = 0L

    fun start(scope: CoroutineScope) {
        stop()
        syncLoopJob = scope.launch { syncLoop() }
        pendingCountJob = scope.launch {
            syncDao.observePendingCount().collect { count ->
                _syncStatus.value = _syncStatus.value.copy(pendingCount = count)
            }
        }
    }

    fun stop() {
        syncLoopJob?.cancel()
        syncLoopJob = null
        pendingCountJob?.cancel()
        pendingCountJob = null
    }

    fun triggerSync() {
        triggerChannel.trySend(Unit)
    }

    private suspend fun syncLoop() {
        while (true) {
            processQueue()
            // Wait for either a trigger or the poll interval, whichever comes first
            select {
                triggerChannel.onReceive {}
                onTimeout(POLL_INTERVAL_MS) {}
            }
        }
    }

    internal suspend fun pruneQueueIfNeeded() {
        val count = syncDao.countAll()
        if (count > MAX_QUEUE_SIZE) {
            val excess = count - MAX_QUEUE_SIZE
            syncDao.pruneOldest(excess)
            Timber.w("Sync queue pruned: removed %d oldest items (was %d, max %d)", excess, count, MAX_QUEUE_SIZE)
        }
    }

    private suspend fun cleanupIfNeeded() {
        val now = System.currentTimeMillis()
        if (now - lastCleanupMs < CLEANUP_INTERVAL_MS) return
        lastCleanupMs = now
        val cutoffMs = now - (appSettingsStore.dataRetentionDays * 24L * 60 * 60 * 1000)
        syncDao.cleanup(maxRetries = MAX_RETRIES, cutoffMs = cutoffMs)
    }

    internal suspend fun processQueue() {
        if (!appSettingsStore.backendSyncEnabled) return
        if (!authTokenStore.hasActiveSession()) return

        // Reset orphaned 'sending' items that got stuck after a crash or cancellation
        syncDao.resetStaleSending(System.currentTimeMillis() - STALE_SENDING_TIMEOUT_MS)

        pruneQueueIfNeeded()
        cleanupIfNeeded()

        val batch = syncDao.getPendingBatch(limit = BATCH_SIZE, maxRetries = MAX_RETRIES)
        if (batch.isEmpty()) return

        val ids = batch.map { it.id }
        val failedParseIds = mutableListOf<Long>()
        syncDao.markSending(ids)

        val adapter = moshi.adapter(PumpEventDto::class.java)
        val events = batch.mapNotNull { entity ->
            try {
                adapter.fromJson(entity.payload)
            } catch (e: Exception) {
                Timber.w(e, "Failed to parse sync queue item %d", entity.id)
                failedParseIds.add(entity.id)
                null
            }
        }

        // Mark unparseable items as permanently failed
        if (failedParseIds.isNotEmpty()) {
            syncDao.markFailed(failedParseIds, "JSON parse error")
        }

        val validIds = ids - failedParseIds.toSet()
        if (events.isEmpty()) return

        // Collect unsent raw history logs to include in the push
        val rawLogs = rawHistoryLogDao.getUnsent(limit = RAW_BATCH_SIZE)
        val rawEventDtos = rawLogs.map { log ->
            PumpRawEventDto(
                sequenceNumber = log.sequenceNumber,
                rawBytesB64 = log.rawBytesB64,
                eventTypeId = log.eventTypeId,
                pumpTimeSeconds = log.pumpTimeSeconds,
            )
        }

        // Map cached hardware info to DTO
        val hardwareDto = cachedHardwareInfo?.let { info ->
            PumpHardwareInfoDto(
                serialNumber = info.serialNumber,
                modelNumber = info.modelNumber,
                partNumber = info.partNumber,
                pumpRev = info.pumpRev,
                armSwVer = info.armSwVer,
                mspSwVer = info.mspSwVer,
                configABits = info.configABits,
                configBBits = info.configBBits,
                pcbaSn = info.pcbaSn,
                pcbaRev = info.pcbaRev,
                pumpFeatures = info.pumpFeatures,
            )
        }

        try {
            val request = PumpPushRequest(
                events = events,
                rawEvents = rawEventDtos.ifEmpty { null },
                pumpInfo = hardwareDto,
            )
            val response = api.pushPumpEvents(request)
            if (response.isSuccessful) {
                syncDao.deleteSent(validIds.toList())
                // Mark raw logs as sent on success
                if (rawLogs.isNotEmpty()) {
                    rawHistoryLogDao.markSent(rawLogs.map { it.id })
                }
                _syncStatus.value = _syncStatus.value.copy(
                    lastSyncAtMs = System.currentTimeMillis(),
                    lastError = null,
                )
                Timber.d(
                    "Sync push: accepted=%d, duplicates=%d, raw_accepted=%d, raw_duplicates=%d",
                    response.body()?.accepted ?: 0,
                    response.body()?.duplicates ?: 0,
                    response.body()?.rawAccepted ?: 0,
                    response.body()?.rawDuplicates ?: 0,
                )
            } else {
                val error = "HTTP ${response.code()}"
                syncDao.markFailed(validIds.toList(), error)
                _syncStatus.value = _syncStatus.value.copy(lastError = error)
                Timber.w("Sync push failed: %s", error)
            }
        } catch (e: Exception) {
            val error = e.message ?: "Unknown network error"
            syncDao.markFailed(validIds.toList(), error)
            _syncStatus.value = _syncStatus.value.copy(lastError = error)
            Timber.w(e, "Sync push network error")
        }
    }
}
