/*
 * GlycemicGPT code (GPL-3.0). Read-only insulin capability for the Medtronic 700-series driver.
 */
package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.ble.messages.MedtronicHistoryParser
import com.glycemicgpt.mobile.ble.read.MedtronicReadGateway
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BolusEvent
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
     * Boluses delivered at or after [since]. Reads the available history log and extracts delivered
     * boluses via [MedtronicHistoryParser], applying [limits] (over-cap boluses are dropped, not
     * clamped).
     *
     * This scans from the start of the available window (sequence 0) and filters by time, so it is
     * O(all-history) per call. `TODO(48.D)`: the polling orchestrator should drive incremental bolus
     * sync through the sequence cursor on
     * [com.glycemicgpt.mobile.domain.plugin.capabilities.PumpStatus.getHistoryLogs] +
     * [com.glycemicgpt.mobile.domain.plugin.capabilities.PumpStatus.extractBolusesFromHistoryLogs]
     * rather than this full-window convenience path.
     */
    override suspend fun getBolusHistory(
        since: Instant,
        limits: SafetyLimits,
    ): Result<List<BolusEvent>> =
        gateway.getHistoryLogs(sinceSequence = 0).map { records ->
            MedtronicHistoryParser.extractBolusesFromHistoryLogs(records, limits)
                .filter { !it.timestamp.isBefore(since) }
        }
}
