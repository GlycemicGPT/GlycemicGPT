/*
 * SG / CGM reader for the Medtronic MiniMed 700-series read-only driver.
 *
 * GlycemicGPT code (GPL-3.0). The read flow -- read the CGM Feature for the E2E-CRC flag, then RACP
 * "report last stored record" to pull the latest measurement -- is ported from OpenMinimed
 * PythonPumpConnector `sg_reader.py` (SGReader), GPL-3.0, used with the author's permission.
 * Copyright (C) OpenMinimed contributors: palmarci (Pal Marci), drfubar, Morten Fyhn Amundsen,
 * Stenium; original medtronic-bt-decrypt PoC by @planiitis. GlycemicGPT is itself GPL-3.0.
 *
 * Crucially, the E2E-CRC use is read from the CGM Feature characteristic per pump rather than
 * hard-coded for 780G as upstream does (medtronic-ble-reverse-engineering.md Sec. 9).
 */
package com.glycemicgpt.mobile.ble.read

import com.glycemicgpt.mobile.ble.protocol.MedtronicProtocol
import com.glycemicgpt.mobile.ble.sake.MedtronicSakeSession
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import java.time.Instant
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * Reads the latest sensor glucose as a [CgmReading] (glucose in **mg/dL**, trend arrow, timestamp).
 *
 * Every value is gated by [safetyLimits]: an out-of-physiological-range glucose is **rejected**, not
 * clamped (a wrong SG is more dangerous than a missing one). Over-the-air behavior rides with 48.A2;
 * nothing here is claimed live-verified.
 *
 * @param now clock for stamping the reading. "Report last stored record" returns the most recent
 *     measurement, so the read time approximates its capture time; per-record absolute timestamps
 *     via the CGM Session Start Time characteristic are a later (48.C2/D) refinement.
 */
class CgmReader(
    private val link: MedtronicGattLink,
    session: MedtronicSakeSession,
    private val safetyLimits: SafetyLimits = SafetyLimits(),
    private val now: () -> Instant = Instant::now,
) {
    private val sessionReader = MedtronicSessionReader(link, session)

    /**
     * Read the CGM Feature flag, then pull and decode the latest measurement into a [CgmReading].
     *
     * The feature flag is static per session; re-reading it on each call is acceptable for this
     * single-shot read but should be cached once polling is added in Milestone D.
     */
    fun readLatest(onResult: (Result<CgmReading>) -> Unit) {
        val useCrc =
            try {
                CgmFeature.parse(link.read(MedtronicProtocol.CGM_FEATURE_UUID)).e2eCrcEnabled
            } catch (e: MedtronicReadException) {
                onResult(Result.failure(e))
                return
            }

        sessionReader.reportLastRecord(
            dataChar = MedtronicProtocol.CGM_MEASUREMENT_UUID,
            controlPoint = MedtronicProtocol.RACP_UUID,
        ) { result ->
            onResult(result.mapCatching { record -> toReading(record, useCrc) })
        }
    }

    private fun toReading(record: ByteArray, useCrc: Boolean): CgmReading {
        val measurement = CgmMeasurement.parse(record, useCrc)
        // TODO(48.C2/F): gate on the sensor-status annunciation (CgmMeasurement.status) so a sensor in
        // warm-up or error doesn't surface a misleading SG.
        if (!measurement.glucoseMgDl.isFinite()) {
            throw MedtronicReadException("SG is a non-finite SFLOAT sentinel (no value)")
        }
        val mgDl = measurement.glucoseMgDl.roundToInt()
        // SafetyLimits is the authoritative reject-not-clamp gate; we check it (and fail with a clear
        // MedtronicReadException) before constructing CgmReading, whose own init re-asserts 20..500.
        // Keep this check: removing it would leak CgmReading's IllegalArgumentException to callers.
        if (mgDl < safetyLimits.minGlucoseMgDl || mgDl > safetyLimits.maxGlucoseMgDl) {
            throw MedtronicReadException(
                "SG $mgDl mg/dL outside safe range " +
                    "${safetyLimits.minGlucoseMgDl}..${safetyLimits.maxGlucoseMgDl}",
            )
        }
        return CgmReading(
            glucoseMgDl = mgDl,
            trendArrow = trendArrowFor(measurement.trendMgDlPerMin),
            timestamp = now(),
        )
    }

    companion object {
        /**
         * Map the CGM rate of change (mg/dL/min) onto the app-wide 7-state [CgmTrend]. The thresholds
         * follow the 780G manual (1-2 / 2-3 / >3 mg/dL/min = 1 / 2 / 3 arrows), folding Medtronic's
         * three-arrow scale onto the Dexcom-style enum: 3 arrows -> DOUBLE, 2 -> SINGLE, 1 -> 45deg.
         * A measurement without trend information, or a non-finite SFLOAT sentinel, is
         * [CgmTrend.UNKNOWN].
         */
        internal fun trendArrowFor(ratePerMin: Double?): CgmTrend {
            if (ratePerMin == null || !ratePerMin.isFinite()) return CgmTrend.UNKNOWN
            val magnitude = abs(ratePerMin)
            return when {
                magnitude < 1.0 -> CgmTrend.FLAT
                ratePerMin > 0 ->
                    when {
                        magnitude >= 3.0 -> CgmTrend.DOUBLE_UP
                        magnitude >= 2.0 -> CgmTrend.SINGLE_UP
                        else -> CgmTrend.FORTY_FIVE_UP
                    }
                else ->
                    when {
                        magnitude >= 3.0 -> CgmTrend.DOUBLE_DOWN
                        magnitude >= 2.0 -> CgmTrend.SINGLE_DOWN
                        else -> CgmTrend.FORTY_FIVE_DOWN
                    }
            }
        }
    }
}
