package com.glycemicgpt.mobile.domain.pump

import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BatteryStatus
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.model.HistoryLogRecord
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.model.PumpHardwareInfo
import com.glycemicgpt.mobile.domain.model.PumpSettings
import com.glycemicgpt.mobile.domain.model.ReservoirReading
import kotlinx.coroutines.flow.Flow
import java.time.Instant

/**
 * Abstract pump driver interface for read-only pump data access.
 *
 * This interface intentionally has NO methods for insulin delivery,
 * pump setting changes, or any control operations. All methods are
 * strictly read-only status queries.
 *
 * Implementations:
 * - [com.glycemicgpt.mobile.ble.connection.TandemBleDriver] for Tandem t:slim X2
 * - Future: OmnipodDriver, MedtronicDriver, etc.
 */
interface PumpDriver {
    suspend fun connect(deviceAddress: String): Result<Unit>
    suspend fun disconnect(): Result<Unit>
    suspend fun getIoB(): Result<IoBReading>
    suspend fun getBasalRate(): Result<BasalReading>
    suspend fun getBolusHistory(since: Instant, limits: SafetyLimits = SafetyLimits()): Result<List<BolusEvent>>
    suspend fun getPumpSettings(): Result<PumpSettings>
    suspend fun getBatteryStatus(): Result<BatteryStatus>
    suspend fun getReservoirLevel(): Result<ReservoirReading>
    suspend fun getCgmStatus(): Result<CgmReading>
    suspend fun getHistoryLogs(sinceSequence: Int): Result<List<HistoryLogRecord>>
    suspend fun getPumpHardwareInfo(): Result<PumpHardwareInfo>
    fun observeConnectionState(): Flow<ConnectionState>
}
