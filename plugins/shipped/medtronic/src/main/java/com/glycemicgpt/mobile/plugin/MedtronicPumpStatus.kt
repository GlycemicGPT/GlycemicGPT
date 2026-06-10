/*
 * GlycemicGPT code (GPL-3.0). Read-only pump-status capability for the Medtronic 700-series driver.
 */
package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.ble.connection.MedtronicBleConnectionManager
import com.glycemicgpt.mobile.ble.messages.MedtronicHistoryParser
import com.glycemicgpt.mobile.ble.read.MedtronicReadGateway
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BatteryStatus
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.HistoryLogRecord
import com.glycemicgpt.mobile.domain.model.PumpHardwareInfo
import com.glycemicgpt.mobile.domain.model.PumpSettings
import com.glycemicgpt.mobile.domain.model.ReservoirReading
import com.glycemicgpt.mobile.domain.plugin.capabilities.PumpStatus
import com.glycemicgpt.mobile.domain.pump.SafetyLimits

/**
 * Exposes battery, reservoir, settings, hardware info and the event-log history as the platform
 * [PumpStatus], delegating reads to [MedtronicReadGateway] and pairing lifecycle to
 * [MedtronicBleConnectionManager]. Read-only: no method writes to the pump.
 *
 * Settings and hardware info both derive from the Device Information Service (Medtronic exposes no
 * dedicated settings characteristic); [toPumpSettings] / [toPumpHardwareInfo] adapt the native shape.
 * The `extract*FromHistoryLogs` helpers are pure functions on [MedtronicHistoryParser] and run on
 * already-fetched raw records, so they need no live session.
 */
class MedtronicPumpStatus(
    private val gateway: MedtronicReadGateway,
    private val connectionManager: MedtronicBleConnectionManager,
) : PumpStatus {

    override suspend fun getBatteryStatus(): Result<BatteryStatus> =
        gateway.getBatteryStatus()

    override suspend fun getReservoirLevel(): Result<ReservoirReading> =
        gateway.getReservoirLevel()

    override suspend fun getPumpSettings(): Result<PumpSettings> =
        gateway.getDeviceInfo().map { it.toPumpSettings() }

    override suspend fun getPumpHardwareInfo(): Result<PumpHardwareInfo> =
        gateway.getDeviceInfo().map { it.toPumpHardwareInfo() }

    override suspend fun getHistoryLogs(sinceSequence: Int): Result<List<HistoryLogRecord>> =
        gateway.getHistoryLogs(sinceSequence)

    override fun extractCgmFromHistoryLogs(
        records: List<HistoryLogRecord>,
        limits: SafetyLimits,
    ): List<CgmReading> =
        MedtronicHistoryParser.extractCgmFromHistoryLogs(records, limits)

    override fun extractBolusesFromHistoryLogs(
        records: List<HistoryLogRecord>,
        limits: SafetyLimits,
    ): List<BolusEvent> =
        MedtronicHistoryParser.extractBolusesFromHistoryLogs(records, limits)

    override fun extractBasalFromHistoryLogs(
        records: List<HistoryLogRecord>,
        limits: SafetyLimits,
    ): List<BasalReading> =
        MedtronicHistoryParser.extractBasalFromHistoryLogs(records, limits)

    override fun unpair() =
        connectionManager.unpair()

    override fun autoReconnectIfPaired() =
        connectionManager.reconnectIfPaired()
}
