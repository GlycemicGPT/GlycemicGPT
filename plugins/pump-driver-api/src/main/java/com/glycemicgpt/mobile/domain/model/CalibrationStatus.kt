package com.glycemicgpt.mobile.domain.model

import java.time.Instant

/**
 * Calibration state of a CGM device.
 */
data class CalibrationStatus(
    val lastCalibrationTime: Instant?,
    val isCalibrationNeeded: Boolean,
    val nextCalibrationDue: Instant?,
)
