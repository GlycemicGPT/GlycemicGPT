package com.glycemicgpt.weardevice.util

import android.graphics.Color
import java.util.Locale

object GlucoseDisplayUtils {

    /**
     * 1 mmol/L = 18.0156 mg/dL -- the exact glucose mass-to-molarity factor and
     * the single canonical constant. Pinned to match the phone
     * `GlucoseFormat.MGDL_PER_MMOL` (and the backend `MGDL_PER_MMOL`) exactly:
     * a drift here would let the watch read a different number than the phone
     * for the same mg/dL. Never introduce a second value (18.02 / 18.0182).
     */
    const val MGDL_PER_MMOL: Double = 18.0156

    fun isValidGlucose(mgDl: Int): Boolean = mgDl in 20..500

    data class Thresholds(val low: Int, val high: Int, val urgentLow: Int, val urgentHigh: Int)

    fun sanitizeThresholds(
        rawLow: Int,
        rawHigh: Int,
        rawUrgentLow: Int,
        rawUrgentHigh: Int,
    ): Thresholds {
        val low = rawLow.coerceIn(40, 200)
        val high = rawHigh.coerceIn(maxOf(low + 1, 100), 400)
        val urgentLow = rawUrgentLow.coerceIn(20, low)
        val urgentHigh = rawUrgentHigh.coerceIn(high, 500)
        return Thresholds(low, high, urgentLow, urgentHigh)
    }

    fun bgColor(mgDl: Int, low: Int, high: Int, urgentLow: Int, urgentHigh: Int): Int {
        return when {
            mgDl <= urgentLow || mgDl >= urgentHigh -> 0xFFEF4444.toInt() // Red
            mgDl <= low || mgDl >= high -> 0xFFEAB308.toInt()              // Yellow
            else -> 0xFF22C55E.toInt()                                      // Green
        }
    }

    // --- Display-only unit formatting (everything above stays canonical mg/dL) ---

    /** User-facing unit label: `"mg/dL"` / `"mmol/L"`. */
    fun unitLabel(unit: GlucoseUnit): String = when (unit) {
        GlucoseUnit.MGDL -> "mg/dL"
        GlucoseUnit.MMOL -> "mmol/L"
    }

    /**
     * Convert a canonical mg/dL Int to the bare number shown in [unit]: the raw
     * integer for mg/dL, or one-decimal mmol/L (divide by [MGDL_PER_MMOL] once,
     * round LAST). [Locale.US] keeps the decimal separator a dot, matching the
     * phone formatter exactly.
     *
     * Display-only: never feed the result back into [isValidGlucose], [bgColor],
     * [sanitizeThresholds], or any plotting geometry -- those all stay mg/dL.
     */
    fun formatGlucose(mgDl: Int, unit: GlucoseUnit): String = when (unit) {
        GlucoseUnit.MGDL -> mgDl.toString()
        GlucoseUnit.MMOL -> String.format(Locale.US, "%.1f", mgDl / MGDL_PER_MMOL)
    }

    /** A glucose number with its unit label, e.g. `"120 mg/dL"` / `"6.7 mmol/L"`. */
    fun formatWithLabel(mgDl: Int, unit: GlucoseUnit): String =
        "${formatGlucose(mgDl, unit)} ${unitLabel(unit)}"

    fun alertColor(type: String): Int {
        return when (type) {
            "urgent_low", "urgent_high" -> 0xFFEF4444.toInt() // Red
            "low", "high" -> 0xFFEAB308.toInt()                // Yellow
            else -> Color.WHITE
        }
    }

    fun trendSymbol(trend: String): String {
        return when (trend) {
            "DOUBLE_UP" -> "\u21C8"       // upwards paired arrows
            "SINGLE_UP" -> "\u2191"        // upwards arrow
            "FORTY_FIVE_UP" -> "\u2197"    // north east arrow
            "FLAT" -> "\u2192"             // rightwards arrow
            "FORTY_FIVE_DOWN" -> "\u2198"  // south east arrow
            "SINGLE_DOWN" -> "\u2193"      // downwards arrow
            "DOUBLE_DOWN" -> "\u21CA"      // downwards paired arrows
            else -> "?"
        }
    }

    fun formatAge(ageMs: Long): String {
        if (ageMs < 0) return "just now"
        val minutes = ageMs / 60_000
        return when {
            minutes < 1 -> "just now"
            minutes < 60 -> "${minutes}m ago"
            else -> "${minutes / 60}h ${minutes % 60}m ago"
        }
    }

    fun freshnessColor(ageMs: Long): Int {
        val minutes = ageMs / 60_000
        return when {
            minutes < 2 -> 0xFF22C55E.toInt()   // Green
            minutes < 10 -> 0xFFF97316.toInt()   // Orange
            else -> 0xFFEF4444.toInt()            // Red
        }
    }
}
