package com.glycemicgpt.mobile.domain.plugin.capabilities

import com.glycemicgpt.mobile.domain.model.CalibrationStatus
import com.glycemicgpt.mobile.domain.plugin.PluginCapabilityInterface
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import java.time.Instant

/**
 * Capability for plugins (typically CGMs) that accept calibration from
 * fingerstick BGM readings.
 *
 * The platform validates [bgValueMgDl] against absolute glucose bounds
 * ([SafetyLimits.ABSOLUTE_MIN_GLUCOSE]..[SafetyLimits.ABSOLUTE_MAX_GLUCOSE])
 * before forwarding to the plugin. Implementations should not need to
 * re-validate these bounds, but may enforce tighter device-specific limits.
 */
interface CalibrationTarget : PluginCapabilityInterface {
    /**
     * Send a calibration reading to the device.
     *
     * @param bgValueMgDl blood glucose value in mg/dL. Must be within
     *   [SafetyLimits.ABSOLUTE_MIN_GLUCOSE]..[SafetyLimits.ABSOLUTE_MAX_GLUCOSE].
     * @param timestamp when the fingerstick was taken.
     */
    suspend fun calibrate(bgValueMgDl: Int, timestamp: Instant): Result<Unit>

    /** Get the current calibration status. */
    suspend fun getCalibrationStatus(): Result<CalibrationStatus>

    companion object {
        /**
         * Validate a BG calibration value against absolute safety bounds.
         * Returns a [Result.failure] if the value is out of range.
         */
        fun validateBgValue(bgValueMgDl: Int): Result<Unit> {
            if (bgValueMgDl !in SafetyLimits.ABSOLUTE_MIN_GLUCOSE..SafetyLimits.ABSOLUTE_MAX_GLUCOSE) {
                return Result.failure(
                    IllegalArgumentException(
                        "BG calibration value $bgValueMgDl outside safe range " +
                            "[${SafetyLimits.ABSOLUTE_MIN_GLUCOSE}..${SafetyLimits.ABSOLUTE_MAX_GLUCOSE}]",
                    ),
                )
            }
            return Result.success(Unit)
        }
    }
}
