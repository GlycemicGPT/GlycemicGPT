package com.glycemicgpt.mobile.domain.plugin.events

import com.glycemicgpt.mobile.domain.model.BgmReading
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import java.time.Instant

/**
 * Events flowing through the [PluginEventBus]. Enables cross-plugin
 * communication (e.g. BGM -> CGM calibration) without direct coupling.
 */
sealed class PluginEvent {
    abstract val pluginId: String

    // -- Device events --

    data class NewGlucoseReading(
        override val pluginId: String,
        val reading: CgmReading,
    ) : PluginEvent()

    data class NewBgmReading(
        override val pluginId: String,
        val reading: BgmReading,
    ) : PluginEvent()

    data class InsulinDelivered(
        override val pluginId: String,
        val event: BolusEvent,
    ) : PluginEvent()

    data class DeviceConnected(
        override val pluginId: String,
    ) : PluginEvent()

    data class DeviceDisconnected(
        override val pluginId: String,
    ) : PluginEvent()

    // -- Calibration events --

    data class CalibrationRequested(
        override val pluginId: String,
        val bgValueMgDl: Int,
        val timestamp: Instant,
    ) : PluginEvent() {
        init {
            require(bgValueMgDl in 20..500) {
                "bgValueMgDl must be in 20..500, was $bgValueMgDl"
            }
        }
    }

    data class CalibrationCompleted(
        override val pluginId: String,
        val success: Boolean,
        val message: String,
    ) : PluginEvent()

    // -- Platform-only events (only publishable by the platform, not plugins) --

    data class SafetyLimitsChanged(
        override val pluginId: String,
        val limits: SafetyLimits,
    ) : PluginEvent()

    companion object {
        /** Event types that only the platform may publish. */
        val PLATFORM_ONLY: Set<kotlin.reflect.KClass<out PluginEvent>> = setOf(
            SafetyLimitsChanged::class,
        )
    }
}
