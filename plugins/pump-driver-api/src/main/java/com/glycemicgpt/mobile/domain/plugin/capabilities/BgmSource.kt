package com.glycemicgpt.mobile.domain.plugin.capabilities

import com.glycemicgpt.mobile.domain.model.BgmReading
import com.glycemicgpt.mobile.domain.plugin.PluginCapabilityInterface
import kotlinx.coroutines.flow.Flow

/**
 * Capability for plugins that provide fingerstick blood glucose readings.
 * Examples: Contour Next One, AccuChek Guide.
 */
interface BgmSource : PluginCapabilityInterface {
    /** Observable stream of fingerstick readings as they arrive. */
    fun observeReadings(): Flow<BgmReading>

    /** Get the most recent fingerstick reading. */
    suspend fun getLatestReading(): Result<BgmReading>
}
