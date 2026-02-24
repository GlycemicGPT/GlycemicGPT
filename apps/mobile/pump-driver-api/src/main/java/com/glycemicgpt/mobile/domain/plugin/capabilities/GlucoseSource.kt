package com.glycemicgpt.mobile.domain.plugin.capabilities

import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.plugin.PluginCapabilityInterface
import kotlinx.coroutines.flow.Flow

/**
 * Capability for plugins that provide continuous glucose readings.
 * Examples: standalone CGMs (Dexcom G7), pumps that stream CGM data (Tandem t:slim X2).
 */
interface GlucoseSource : PluginCapabilityInterface {
    /** Observable stream of glucose readings as they arrive. */
    fun observeReadings(): Flow<CgmReading>

    /** Get the most recent glucose reading on demand. */
    suspend fun getCurrentReading(): Result<CgmReading>
}
