package com.glycemicgpt.mobile.domain.format

import com.glycemicgpt.mobile.domain.model.GlucoseUnit
import java.util.Locale

/**
 * The single client-side choke-point that turns a stored mg/dL glucose value into
 * the number and label a user reads in their preferred unit.
 *
 * Pure Kotlin (no Android dependencies) so the watch surface can mirror it. mg/dL
 * output is byte-identical to the legacy hand-written strings (integer, `mg/dL`
 * label); mmol/L converts from the most-precise mg/dL source ONCE and rounds to
 * one decimal LAST, so the threshold anchors land on their conventional values
 * (70 -> 3.9, 180 -> 10.0, 120 -> 6.7, 100 -> 5.6). All formatting uses
 * [Locale.US] so the decimal separator is always a dot -- both for cross-surface
 * consistency and so the mmol output still matches the release log scrubber.
 */
object GlucoseFormat {

    /**
     * 1 mmol/L = 18.0156 mg/dL -- the exact glucose mass-to-molarity factor and the
     * single canonical constant. Mirrors the backend `MGDL_PER_MMOL` in
     * `src/core/units.py` and the web `MGDL_PER_MMOL`. Never introduce a second
     * value (18.02 / 18.0182); a drift here desyncs the client from the server.
     */
    const val MGDL_PER_MMOL: Double = 18.0156

    /** User-facing unit label: `"mg/dL"` / `"mmol/L"`. */
    fun label(unit: GlucoseUnit): String = when (unit) {
        GlucoseUnit.MGDL -> "mg/dL"
        GlucoseUnit.MMOL -> "mmol/L"
    }

    /** Spoken (accessibility) unit name (US spelling, matching the mg/dL "deciliter"). */
    fun spokenUnit(unit: GlucoseUnit): String = when (unit) {
        GlucoseUnit.MGDL -> "milligrams per deciliter"
        GlucoseUnit.MMOL -> "millimoles per liter"
    }

    /** The one mg/dL -> mmol/L divide, unrounded (round LAST). Mirrors the backend `mgdl_to_mmol`. */
    private fun mgdlToMmol(valueMgDl: Double): Double = valueMgDl / MGDL_PER_MMOL

    /**
     * Convert a stored mg/dL glucose value to the display unit, without rounding
     * (round LAST at the display edge). mg/dL returns the value verbatim.
     */
    fun convertValue(mgDl: Int, unit: GlucoseUnit): Double = when (unit) {
        GlucoseUnit.MGDL -> mgDl.toDouble()
        GlucoseUnit.MMOL -> mgdlToMmol(mgDl.toDouble())
    }

    /**
     * Convert a glucose *spread* (a standard deviation or any difference of two
     * glucose values) to mmol/L. Offset-free divide-by-factor, deliberately
     * distinct from [convertValue]: a spread has no zero-anchor and, in mg/dL,
     * keeps a decimal where a value is shown as an integer. Reusing the value
     * converter for a spread is a bug.
     */
    fun convertSpread(mgDl: Double): Double = mgdlToMmol(mgDl)

    /** A bare glucose number in [unit] -- integer for mg/dL, one decimal for mmol/L. */
    fun format(mgDl: Int, unit: GlucoseUnit): String = when (unit) {
        GlucoseUnit.MGDL -> mgDl.toString()
        GlucoseUnit.MMOL -> String.format(Locale.US, "%.1f", convertValue(mgDl, unit))
    }

    /** A glucose number with its unit label, e.g. `"120 mg/dL"` / `"6.7 mmol/L"`. */
    fun formatWithLabel(mgDl: Int, unit: GlucoseUnit): String =
        "${format(mgDl, unit)} ${label(unit)}"

    /**
     * Format a mean glucose (a `Float` already in mg/dL): an integer for mg/dL --
     * byte-identical to the legacy `"%.0f"` -- and one decimal for mmol/L.
     */
    fun formatMean(meanMgDl: Float, unit: GlucoseUnit): String = when (unit) {
        GlucoseUnit.MGDL -> String.format(Locale.US, "%.0f", meanMgDl)
        GlucoseUnit.MMOL -> String.format(Locale.US, "%.1f", mgdlToMmol(meanMgDl.toDouble()))
    }

    /**
     * Format a glucose spread (a `Float` standard deviation in mg/dL): one decimal
     * in either unit. mmol/L goes through [convertSpread], never [convertValue].
     */
    fun formatSpread(spreadMgDl: Float, unit: GlucoseUnit): String = when (unit) {
        GlucoseUnit.MGDL -> String.format(Locale.US, "%.1f", spreadMgDl)
        GlucoseUnit.MMOL -> String.format(Locale.US, "%.1f", convertSpread(spreadMgDl.toDouble()))
    }
}
