package com.glycemicgpt.mobile.plugin.adapter

import com.glycemicgpt.mobile.domain.model.BatteryStatus
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.model.HistoryLogRecord
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.model.PumpHardwareInfo
import com.glycemicgpt.mobile.domain.model.PumpSettings
import com.glycemicgpt.mobile.domain.model.ReservoirReading
import com.glycemicgpt.mobile.domain.plugin.asGlucoseSource
import com.glycemicgpt.mobile.domain.plugin.asInsulinSource
import com.glycemicgpt.mobile.domain.plugin.asPumpStatus
import com.glycemicgpt.mobile.domain.pump.PumpDriver
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import com.glycemicgpt.mobile.plugin.PluginRegistry
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import java.time.Instant
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Bridges the deprecated [PumpDriver] interface to the plugin registry.
 * Existing consumers (HomeViewModel, PumpPollingOrchestrator, etc.) keep
 * working without code changes.
 */
@Suppress("DEPRECATION")
@Singleton
class PumpDriverAdapter @Inject constructor(
    private val registry: PluginRegistry,
) : PumpDriver {

    override suspend fun connect(deviceAddress: String): Result<Unit> {
        val plugin = registry.activePumpPlugin.value
            ?: return Result.failure(NoActivePluginException())
        return try {
            plugin.connect(deviceAddress)
            Result.success(Unit)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun disconnect(): Result<Unit> {
        val plugin = registry.activePumpPlugin.value
            ?: return Result.failure(NoActivePluginException())
        return try {
            plugin.disconnect()
            Result.success(Unit)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getIoB(): Result<IoBReading> =
        registry.activePumpPlugin.value?.asInsulinSource()?.getIoB()
            ?: Result.failure(NoActivePluginException())

    override suspend fun getBasalRate(): Result<BasalReading> =
        registry.activePumpPlugin.value?.asInsulinSource()?.getBasalRate()
            ?: Result.failure(NoActivePluginException())

    override suspend fun getBolusHistory(since: Instant, limits: SafetyLimits): Result<List<BolusEvent>> =
        registry.activePumpPlugin.value?.asInsulinSource()?.getBolusHistory(since, limits)
            ?: Result.failure(NoActivePluginException())

    override suspend fun getPumpSettings(): Result<PumpSettings> =
        registry.activePumpPlugin.value?.asPumpStatus()?.getPumpSettings()
            ?: Result.failure(NoActivePluginException())

    override suspend fun getBatteryStatus(): Result<BatteryStatus> =
        registry.activePumpPlugin.value?.asPumpStatus()?.getBatteryStatus()
            ?: Result.failure(NoActivePluginException())

    override suspend fun getReservoirLevel(): Result<ReservoirReading> =
        registry.activePumpPlugin.value?.asPumpStatus()?.getReservoirLevel()
            ?: Result.failure(NoActivePluginException())

    override suspend fun getCgmStatus(): Result<CgmReading> =
        registry.activeGlucoseSource.value?.asGlucoseSource()?.getCurrentReading()
            ?: Result.failure(NoActivePluginException())

    override suspend fun getHistoryLogs(sinceSequence: Int): Result<List<HistoryLogRecord>> =
        registry.activePumpPlugin.value?.asPumpStatus()?.getHistoryLogs(sinceSequence)
            ?: Result.failure(NoActivePluginException())

    override suspend fun getPumpHardwareInfo(): Result<PumpHardwareInfo> =
        registry.activePumpPlugin.value?.asPumpStatus()?.getPumpHardwareInfo()
            ?: Result.failure(NoActivePluginException())

    @OptIn(ExperimentalCoroutinesApi::class)
    override fun observeConnectionState(): Flow<ConnectionState> =
        registry.activePumpPlugin.flatMapLatest { plugin ->
            plugin?.observeConnectionState() ?: flowOf(ConnectionState.DISCONNECTED)
        }
}
