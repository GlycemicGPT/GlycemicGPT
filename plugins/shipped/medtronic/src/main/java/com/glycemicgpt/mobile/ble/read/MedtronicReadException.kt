/*
 * GlycemicGPT code (GPL-3.0). Failure type for the Medtronic 700-series read layer.
 */
package com.glycemicgpt.mobile.ble.read

/**
 * Thrown when a Medtronic pump payload cannot be turned into a trustworthy domain value: a malformed
 * or truncated frame, a failed E2E-CRC, an unexpected control-point response, or a reading that
 * falls outside the configured [com.glycemicgpt.mobile.domain.pump.SafetyLimits].
 *
 * The read layer **rejects** rather than clamps: a value we cannot fully trust is never silently
 * coerced into range, because a wrong glucose or battery number is worse than a missing one.
 */
class MedtronicReadException(message: String, cause: Throwable? = null) : Exception(message, cause)
