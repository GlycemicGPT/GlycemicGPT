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
     * Sequence cursor for the medium-tier bolus poll: the highest history sequence already fetched by
     * *this* path. Each poll asks the pump only for records newer than it, so the poll is an incremental
     * delta rather than a full-window rescan. Single-writer -- only the orchestrator's medium loop calls
     * [getBolusHistory] and the gateway serializes wire access, so the volatile here is for restart
     * visibility, not concurrent read-modify-write safety (mirrors [com.glycemicgpt.mobile.ble.connection]'s
     * single-writer `@Volatile` cursors).
     *
     * Best-effort, not the durable bolus record: it advances on a successful fetch, before the
     * orchestrator persists, so a transient save failure could skip a bolus on this path. That is
     * tolerated because the **slow loop's raw-history sync is the durable, self-healing bolus path** --
     * it persists each raw [HistoryLogRecord] to Room (keyed by sequence) before advancing its own
     * cursor, restores that cursor from Room on restart, and re-extracts the same boluses from the same
     * IDD stream. Persisted bolus rows are de-duplicated by the repository's insert-conflict key, so the
     * one-time full re-read after a restart (cursor 0) yields no duplicate rows.
     */
    @Volatile
    private var bolusCursor: Int = 0

    /**
     * Boluses delivered at or after [since]. Fetches only the history records newer than [bolusCursor]
     * (the pump's RACP range query), advances the cursor past the records seen, extracts delivered
     * boluses via [MedtronicHistoryParser] applying [limits] (over-cap boluses are dropped, not
     * clamped), and filters by [since] as a defensive lower bound.
     *
     * This replaces the earlier O(all-history) `getHistoryLogs(sinceSequence = 0)` full-window scan
     * (closing the C3 cost note): each medium poll is now an incremental delta over the same IDD stream
     * the slow loop backfills. See [bolusCursor] for the durability / dedup model.
     */
    override suspend fun getBolusHistory(
        since: Instant,
        limits: SafetyLimits,
    ): Result<List<BolusEvent>> =
        gateway.getHistoryLogs(sinceSequence = bolusCursor).map { records ->
            bolusCursor = records.maxOfOrNull { it.sequenceNumber } ?: bolusCursor
            MedtronicHistoryParser.extractBolusesFromHistoryLogs(records, limits)
                .filter { !it.timestamp.isBefore(since) }
        }
}
