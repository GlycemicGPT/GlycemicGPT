/*
 * GlycemicGPT code (GPL-3.0). Read-only insulin capability for the Medtronic 700-series driver.
 */
package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.ble.messages.MedtronicHistoryParser
import com.glycemicgpt.mobile.ble.read.MedtronicReadGateway
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.HistoryLogRecord
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.plugin.capabilities.InsulinSource
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.time.Instant

/**
 * Exposes IOB, active basal rate and bolus history as the platform [InsulinSource], delegating to
 * [MedtronicReadGateway]. Read-only: no method writes to the pump.
 */
class MedtronicInsulinSource(
    private val gateway: MedtronicReadGateway,
) : InsulinSource {

    override suspend fun getIoB(): Result<IoBReading> =
        gateway.getIoB()

    override suspend fun getBasalRate(): Result<BasalReading> =
        gateway.getBasalRate()

    /**
     * Serializes the [bolusCursor] read-fetch-advance so a fetch and its cursor update are atomic.
     * Capability methods can be called from background dispatchers, so even though the orchestrator
     * polls boluses from a single loop today, two concurrent [getBolusHistory] calls must not both read
     * the same cursor, fetch overlapping windows, and then write back out of order (which would regress
     * the cursor). The gateway's own mutex only serializes one wire exchange, not this read-modify-write.
     */
    private val bolusSyncMutex = Mutex()

    /**
     * Sequence cursor for the medium-tier bolus poll: the highest history sequence already fetched by
     * *this* path. Each poll asks the pump only for records newer than it, so the poll is an incremental
     * delta rather than a full-window rescan. Guarded by [bolusSyncMutex] -- only read/written while that
     * lock is held -- so the read-modify-write is safe regardless of how many coroutines call
     * [getBolusHistory].
     *
     * Best-effort, not the durable bolus record: it advances on a successful fetch, before the
     * orchestrator persists, so a transient save failure could skip a bolus on this path. That is
     * tolerated because the **slow loop's raw-history sync is the durable, self-healing bolus path** --
     * it persists each raw [HistoryLogRecord] to Room (keyed by sequence) before advancing its own
     * cursor, restores that cursor from Room on restart, and re-extracts the same boluses from the same
     * IDD stream. Persisted bolus rows are de-duplicated by the repository's insert-conflict key, so the
     * one-time full re-read after a restart (cursor 0) yields no duplicate rows.
     */
    private var bolusCursor: Int = 0

    /**
     * Boluses delivered at or after [since]. Fetches only the history records newer than [bolusCursor]
     * (the pump's RACP range query), advances the cursor past the records seen, extracts delivered
     * boluses via [MedtronicHistoryParser] applying [limits] (over-cap boluses are dropped, not
     * clamped), and filters by [since] as a defensive lower bound. The whole read-fetch-advance runs
     * under [bolusSyncMutex] so concurrent calls can never regress the cursor or fetch overlapping
     * windows.
     *
     * This replaces the earlier O(all-history) `getHistoryLogs(sinceSequence = 0)` full-window scan
     * (closing the C3 cost note): each medium poll is now an incremental delta over the same IDD stream
     * the slow loop backfills. See [bolusCursor] for the durability / dedup model.
     */
    override suspend fun getBolusHistory(
        since: Instant,
        limits: SafetyLimits,
    ): Result<List<BolusEvent>> =
        bolusSyncMutex.withLock {
            gateway.getHistoryLogs(sinceSequence = bolusCursor).map { records ->
                bolusCursor = records.maxOfOrNull { it.sequenceNumber } ?: bolusCursor
                MedtronicHistoryParser.extractBolusesFromHistoryLogs(records, limits)
                    .filter { !it.timestamp.isBefore(since) }
            }
        }
}
