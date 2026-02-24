package com.glycemicgpt.mobile.domain.plugin.capabilities

import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BatteryStatus
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.HistoryLogRecord
import com.glycemicgpt.mobile.domain.model.PumpHardwareInfo
import com.glycemicgpt.mobile.domain.model.PumpSettings
import com.glycemicgpt.mobile.domain.model.ReservoirReading
import com.glycemicgpt.mobile.domain.plugin.PluginCapabilityInterface
import com.glycemicgpt.mobile.domain.pump.SafetyLimits

/**
 * Capability for plugins that provide pump hardware status and history data (read-only).
 */
interface PumpStatus : PluginCapabilityInterface {
    suspend fun getBatteryStatus(): Result<BatteryStatus>
    suspend fun getReservoirLevel(): Result<ReservoirReading>
    suspend fun getPumpSettings(): Result<PumpSettings>
    suspend fun getPumpHardwareInfo(): Result<PumpHardwareInfo>
    suspend fun getHistoryLogs(sinceSequence: Int): Result<List<HistoryLogRecord>>

    /**
     * Extracts CGM readings from [records], applying [limits] to filter out any reading
     * whose glucose value falls outside [SafetyLimits.glucoseLow]..[SafetyLimits.glucoseHigh]
     * (or at minimum the absolute range 20-500 mg/dL). Out-of-range records must be dropped,
     * not clamped.
     */
    fun extractCgmFromHistoryLogs(
        records: List<HistoryLogRecord>,
        limits: SafetyLimits,
    ): List<CgmReading>

    /**
     * Extracts bolus events from [records]. Implementations MUST reject any event whose
     * [BolusEvent.units] exceeds [SafetyLimits.maxBolus]; such records must be dropped
     * and never returned to the caller.
     */
    fun extractBolusesFromHistoryLogs(
        records: List<HistoryLogRecord>,
        limits: SafetyLimits,
    ): List<BolusEvent>

    /**
     * Extracts basal readings from [records], applying any applicable rate limits from
     * [limits]. Out-of-range entries must be dropped.
     */
    fun extractBasalFromHistoryLogs(
        records: List<HistoryLogRecord>,
        limits: SafetyLimits,
    ): List<BasalReading>

    /**
     * Clear pairing credentials and disconnect.
     *
     * TODO: Make suspend once deprecated PumpConnectionManager is removed.
     * Current implementations (BleConnectionManager) do not require suspension.
     */
    fun unpair()

    /**
     * Attempt to reconnect to a previously paired device.
     *
     * TODO: Make suspend once deprecated PumpConnectionManager is removed.
     * Current implementations (BleConnectionManager) do not require suspension.
     */
    fun autoReconnectIfPaired()
}
