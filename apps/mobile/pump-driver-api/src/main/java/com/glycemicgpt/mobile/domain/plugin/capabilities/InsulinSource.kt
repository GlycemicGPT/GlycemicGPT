package com.glycemicgpt.mobile.domain.plugin.capabilities

import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.plugin.PluginCapabilityInterface
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import java.time.Instant

/**
 * Capability for plugins that provide insulin delivery data (read-only).
 * Examples: insulin pumps, smart pens.
 */
interface InsulinSource : PluginCapabilityInterface {
    suspend fun getIoB(): Result<IoBReading>
    suspend fun getBasalRate(): Result<BasalReading>
    suspend fun getBolusHistory(
        since: Instant,
        limits: SafetyLimits,
    ): Result<List<BolusEvent>>
}
