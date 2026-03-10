package com.glycemicgpt.weardevice.util

import android.graphics.Color

object GlucoseDisplayUtils {

    fun isValidGlucose(mgDl: Int): Boolean = mgDl in 20..500

    fun bgColor(mgDl: Int, low: Int, high: Int, urgentLow: Int, urgentHigh: Int): Int {
        return when {
            mgDl <= urgentLow || mgDl >= urgentHigh -> 0xFFEF4444.toInt() // Red
            mgDl <= low || mgDl >= high -> 0xFFEAB308.toInt()              // Yellow
            else -> 0xFF22C55E.toInt()                                      // Green
        }
    }

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
