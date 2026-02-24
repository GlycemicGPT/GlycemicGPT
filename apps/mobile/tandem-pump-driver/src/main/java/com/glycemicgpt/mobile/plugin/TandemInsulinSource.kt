package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.plugin.capabilities.InsulinSource
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import com.glycemicgpt.mobile.ble.connection.TandemBleDriver
import java.time.Instant

class TandemInsulinSource(
    private val bleDriver: TandemBleDriver,
) : InsulinSource {
    override suspend fun getIoB(): Result<IoBReading> =
        bleDriver.getIoB()

    override suspend fun getBasalRate(): Result<BasalReading> =
        bleDriver.getBasalRate()

    override suspend fun getBolusHistory(
        since: Instant,
        limits: SafetyLimits,
    ): Result<List<BolusEvent>> =
        bleDriver.getBolusHistory(since, limits)
}
