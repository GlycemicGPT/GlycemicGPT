package com.glycemicgpt.mobile.plugin

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
import com.glycemicgpt.mobile.ble.connection.BleConnectionManager
import com.glycemicgpt.mobile.ble.connection.TandemBleDriver
import com.glycemicgpt.mobile.ble.messages.TandemHistoryLogParser

class TandemPumpStatus(
    private val bleDriver: TandemBleDriver,
    private val historyParser: TandemHistoryLogParser,
    private val connectionManager: BleConnectionManager,
) : PumpStatus {
    override suspend fun getBatteryStatus(): Result<BatteryStatus> =
        bleDriver.getBatteryStatus()

    override suspend fun getReservoirLevel(): Result<ReservoirReading> =
        bleDriver.getReservoirLevel()

    override suspend fun getPumpSettings(): Result<PumpSettings> =
        bleDriver.getPumpSettings()

    override suspend fun getPumpHardwareInfo(): Result<PumpHardwareInfo> =
        bleDriver.getPumpHardwareInfo()

    override suspend fun getHistoryLogs(sinceSequence: Int): Result<List<HistoryLogRecord>> =
        bleDriver.getHistoryLogs(sinceSequence)

    override fun extractCgmFromHistoryLogs(
        records: List<HistoryLogRecord>,
        limits: SafetyLimits,
    ): List<CgmReading> =
        historyParser.extractCgmFromHistoryLogs(records, limits)

    override fun extractBolusesFromHistoryLogs(
        records: List<HistoryLogRecord>,
        limits: SafetyLimits,
    ): List<BolusEvent> =
        historyParser.extractBolusesFromHistoryLogs(records, limits)

    override fun extractBasalFromHistoryLogs(
        records: List<HistoryLogRecord>,
        limits: SafetyLimits,
    ): List<BasalReading> =
        historyParser.extractBasalFromHistoryLogs(records, limits)

    override fun unpair() =
        connectionManager.unpair()

    override fun autoReconnectIfPaired() =
        connectionManager.autoReconnectIfPaired()
}
