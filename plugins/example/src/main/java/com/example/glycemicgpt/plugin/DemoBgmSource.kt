package com.example.glycemicgpt.plugin

import com.glycemicgpt.mobile.domain.model.BgmReading
import com.glycemicgpt.mobile.domain.plugin.capabilities.BgmSource
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow

/**
 * [BgmSource] capability implementation for the Demo Glucometer plugin.
 *
 * This demonstrates how a real BGM plugin would implement the BgmSource interface.
 * In a real plugin, [observeReadings] would connect to a Bluetooth glucose meter
 * (e.g., Contour Next One) and stream actual fingerstick readings. Here we delegate
 * to [ReadingSimulator] which generates synthetic data.
 *
 * ## Key implementation notes for plugin authors
 *
 * - [observeReadings] returns a **cold Flow** -- the platform collects it when the
 *   plugin is active. When the plugin is deactivated, collection is cancelled.
 * - [getLatestReading] must be safe to call from any thread (background dispatchers).
 * - All readings must be validated against safety limits before emission. The
 *   [ReadingSimulator] reads the StateFlow's current value on each iteration,
 *   so backend safety limit changes take effect immediately.
 * - The [BgmReading] constructor validates `glucoseMgDl` is in 20..500.
 */
class DemoBgmSource(
    private val simulator: ReadingSimulator,
    private val safetyLimits: StateFlow<SafetyLimits>,
    private val intervalProvider: () -> Long,
) : BgmSource {

    /**
     * Observable stream of simulated fingerstick readings.
     *
     * In a real plugin this would:
     * 1. Discover and connect to the BLE glucose meter
     * 2. Subscribe to the meter's glucose measurement characteristic
     * 3. Parse incoming BLE notifications into [BgmReading] objects
     * 4. Validate each reading against safety limits (read StateFlow.value each time)
     * 5. Emit valid readings to collectors
     */
    override fun observeReadings(): Flow<BgmReading> =
        simulator.start(
            intervalSeconds = intervalProvider(),
            safetyLimits = safetyLimits,
        )

    /**
     * Returns the most recent simulated reading, or failure if none available yet.
     *
     * In a real plugin this might query the meter's stored readings or return
     * a cached value from the last BLE notification.
     */
    override suspend fun getLatestReading(): Result<BgmReading> {
        val reading = simulator.latestReading
            ?: return Result.failure(IllegalStateException("No readings available yet"))
        return Result.success(reading)
    }
}
