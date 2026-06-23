package com.glycemicgpt.weardevice.util

import android.graphics.Color
import java.util.Locale
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GlucoseDisplayUtilsTest {

    // isValidGlucose tests

    @Test
    fun `isValidGlucose returns true for normal range`() {
        assertTrue(GlucoseDisplayUtils.isValidGlucose(120))
    }

    @Test
    fun `isValidGlucose returns true for boundary values`() {
        assertTrue(GlucoseDisplayUtils.isValidGlucose(20))
        assertTrue(GlucoseDisplayUtils.isValidGlucose(500))
    }

    @Test
    fun `isValidGlucose returns false for zero`() {
        assertFalse(GlucoseDisplayUtils.isValidGlucose(0))
    }

    @Test
    fun `isValidGlucose returns false for negative`() {
        assertFalse(GlucoseDisplayUtils.isValidGlucose(-1))
    }

    @Test
    fun `isValidGlucose returns false for too high`() {
        assertFalse(GlucoseDisplayUtils.isValidGlucose(501))
    }

    // bgColor tests

    @Test
    fun `bgColor returns green for in-range value`() {
        val color = GlucoseDisplayUtils.bgColor(mgDl = 120, low = 70, high = 180, urgentLow = 55, urgentHigh = 250)
        assertEquals(0xFF22C55E.toInt(), color)
    }

    @Test
    fun `bgColor returns yellow for high value`() {
        val color = GlucoseDisplayUtils.bgColor(mgDl = 200, low = 70, high = 180, urgentLow = 55, urgentHigh = 250)
        assertEquals(0xFFEAB308.toInt(), color)
    }

    @Test
    fun `bgColor returns yellow for low value`() {
        val color = GlucoseDisplayUtils.bgColor(mgDl = 65, low = 70, high = 180, urgentLow = 55, urgentHigh = 250)
        assertEquals(0xFFEAB308.toInt(), color)
    }

    @Test
    fun `bgColor returns red for urgent high value`() {
        val color = GlucoseDisplayUtils.bgColor(mgDl = 260, low = 70, high = 180, urgentLow = 55, urgentHigh = 250)
        assertEquals(0xFFEF4444.toInt(), color)
    }

    @Test
    fun `bgColor returns red for urgent low value`() {
        val color = GlucoseDisplayUtils.bgColor(mgDl = 50, low = 70, high = 180, urgentLow = 55, urgentHigh = 250)
        assertEquals(0xFFEF4444.toInt(), color)
    }

    @Test
    fun `bgColor at exact low boundary returns yellow`() {
        val color = GlucoseDisplayUtils.bgColor(mgDl = 70, low = 70, high = 180, urgentLow = 55, urgentHigh = 250)
        assertEquals(0xFFEAB308.toInt(), color)
    }

    @Test
    fun `bgColor at exact high boundary returns yellow`() {
        val color = GlucoseDisplayUtils.bgColor(mgDl = 180, low = 70, high = 180, urgentLow = 55, urgentHigh = 250)
        assertEquals(0xFFEAB308.toInt(), color)
    }

    @Test
    fun `bgColor just inside range returns green`() {
        val color = GlucoseDisplayUtils.bgColor(mgDl = 71, low = 70, high = 180, urgentLow = 55, urgentHigh = 250)
        assertEquals(0xFF22C55E.toInt(), color)
    }

    // trendSymbol tests

    @Test
    fun `trendSymbol maps all known trends`() {
        assertEquals("\u21C8", GlucoseDisplayUtils.trendSymbol("DOUBLE_UP"))
        assertEquals("\u2191", GlucoseDisplayUtils.trendSymbol("SINGLE_UP"))
        assertEquals("\u2197", GlucoseDisplayUtils.trendSymbol("FORTY_FIVE_UP"))
        assertEquals("\u2192", GlucoseDisplayUtils.trendSymbol("FLAT"))
        assertEquals("\u2198", GlucoseDisplayUtils.trendSymbol("FORTY_FIVE_DOWN"))
        assertEquals("\u2193", GlucoseDisplayUtils.trendSymbol("SINGLE_DOWN"))
        assertEquals("\u21CA", GlucoseDisplayUtils.trendSymbol("DOUBLE_DOWN"))
    }

    @Test
    fun `trendSymbol returns question mark for unknown`() {
        assertEquals("?", GlucoseDisplayUtils.trendSymbol("UNKNOWN"))
        assertEquals("?", GlucoseDisplayUtils.trendSymbol("BOGUS"))
    }

    // formatAge tests

    @Test
    fun `formatAge returns just now for less than 1 minute`() {
        assertEquals("just now", GlucoseDisplayUtils.formatAge(30_000))
    }

    @Test
    fun `formatAge returns minutes for less than 1 hour`() {
        assertEquals("5m ago", GlucoseDisplayUtils.formatAge(5 * 60_000))
    }

    @Test
    fun `formatAge returns hours and minutes for over 1 hour`() {
        assertEquals("1h 30m ago", GlucoseDisplayUtils.formatAge(90 * 60_000))
    }

    @Test
    fun `formatAge returns just now for negative age (clock skew)`() {
        assertEquals("just now", GlucoseDisplayUtils.formatAge(-5_000))
    }

    // freshnessColor tests

    @Test
    fun `freshnessColor returns green for fresh data`() {
        assertEquals(0xFF22C55E.toInt(), GlucoseDisplayUtils.freshnessColor(60_000))
    }

    @Test
    fun `freshnessColor returns orange for slightly stale data`() {
        assertEquals(0xFFF97316.toInt(), GlucoseDisplayUtils.freshnessColor(5 * 60_000))
    }

    @Test
    fun `freshnessColor returns red for very stale data`() {
        assertEquals(0xFFEF4444.toInt(), GlucoseDisplayUtils.freshnessColor(15 * 60_000))
    }

    // alertColor tests

    @Test
    fun `alertColor returns red for urgent types`() {
        assertEquals(0xFFEF4444.toInt(), GlucoseDisplayUtils.alertColor("urgent_low"))
        assertEquals(0xFFEF4444.toInt(), GlucoseDisplayUtils.alertColor("urgent_high"))
    }

    @Test
    fun `alertColor returns yellow for warning types`() {
        assertEquals(0xFFEAB308.toInt(), GlucoseDisplayUtils.alertColor("low"))
        assertEquals(0xFFEAB308.toInt(), GlucoseDisplayUtils.alertColor("high"))
    }

    @Test
    fun `alertColor returns white for unknown type`() {
        assertEquals(Color.WHITE, GlucoseDisplayUtils.alertColor("unknown"))
    }

    // sanitizeThresholds tests

    @Test
    fun `sanitizeThresholds passes through valid values unchanged`() {
        val t = GlucoseDisplayUtils.sanitizeThresholds(70, 180, 55, 250)
        assertEquals(70, t.low)
        assertEquals(180, t.high)
        assertEquals(55, t.urgentLow)
        assertEquals(250, t.urgentHigh)
    }

    @Test
    fun `sanitizeThresholds enforces ordering when low exceeds high`() {
        val t = GlucoseDisplayUtils.sanitizeThresholds(200, 100, 55, 250)
        assertTrue("low < high", t.low < t.high)
        assertTrue("urgentLow <= low", t.urgentLow <= t.low)
        assertTrue("urgentHigh >= high", t.urgentHigh >= t.high)
    }

    @Test
    fun `sanitizeThresholds clamps extreme values`() {
        val t = GlucoseDisplayUtils.sanitizeThresholds(10, 500, 5, 600)
        assertEquals(40, t.low)
        assertEquals(400, t.high)
        assertEquals(20, t.urgentLow)
        assertEquals(500, t.urgentHigh) // coerceIn(high=400, 500)
    }

    @Test
    fun `sanitizeThresholds high is at least low plus 1`() {
        val t = GlucoseDisplayUtils.sanitizeThresholds(150, 150, 55, 250)
        assertTrue("high > low", t.high > t.low)
    }

    // --- Display-only unit formatting ---

    @Test
    fun `MGDL_PER_MMOL is the canonical 18_0156 constant`() {
        // A drift here desyncs the watch from the phone/backend for the same mg/dL.
        assertEquals(18.0156, GlucoseDisplayUtils.MGDL_PER_MMOL, 0.0)
    }

    @Test
    fun `formatGlucose renders mgdl as the raw integer`() {
        assertEquals("70", GlucoseDisplayUtils.formatGlucose(70, GlucoseUnit.MGDL))
        assertEquals("120", GlucoseDisplayUtils.formatGlucose(120, GlucoseUnit.MGDL))
    }

    @Test
    fun `formatGlucose converts mmol to conventional clinical anchors`() {
        assertEquals("3.9", GlucoseDisplayUtils.formatGlucose(70, GlucoseUnit.MMOL))
        assertEquals("10.0", GlucoseDisplayUtils.formatGlucose(180, GlucoseUnit.MMOL))
        assertEquals("6.7", GlucoseDisplayUtils.formatGlucose(120, GlucoseUnit.MMOL))
        assertEquals("5.6", GlucoseDisplayUtils.formatGlucose(100, GlucoseUnit.MMOL))
    }

    @Test
    fun `mmol fixture matches the cross-surface contract`() {
        // The shared mg/dL -> mmol/L fixture every surface must render the same
        // way: here, the phone (GlucoseFormat.format), the web (formatGlucose ->
        // toFixed(1)), and the API (format_glucose_value). Each string is
        // round(x / 18.0156, 1); none of the 8 lands on a .x5 tie so %.1f, JS
        // toFixed, and Python round all agree.
        val crossSurface = linkedMapOf(
            54 to "3.0",
            70 to "3.9",
            99 to "5.5",
            100 to "5.6",
            120 to "6.7",
            180 to "10.0",
            250 to "13.9",
            400 to "22.2",
        )
        for ((mgDl, expected) in crossSurface) {
            assertEquals("$mgDl mg/dL -> mmol", expected, GlucoseDisplayUtils.formatGlucose(mgDl, GlucoseUnit.MMOL))
            assertEquals("$mgDl mg/dL", mgDl.toString(), GlucoseDisplayUtils.formatGlucose(mgDl, GlucoseUnit.MGDL))
        }
    }

    @Test
    fun `bgColor bands the stored mg-dL value regardless of display unit`() {
        // bgColor takes thresholds and a stored mg/dL reading but NO unit, so the
        // user's mmol/L preference cannot reach it. These values land in the same
        // band on the watch, phone (glucoseColor), and web (classifyGlucose).
        val red = 0xFFEF4444.toInt()
        val yellow = 0xFFEAB308.toInt()
        val green = 0xFF22C55E.toInt()
        fun band(mgDl: Int) =
            GlucoseDisplayUtils.bgColor(mgDl, low = 70, high = 180, urgentLow = 55, urgentHigh = 250)
        assertEquals(red, band(40))
        assertEquals(yellow, band(65))
        assertEquals(green, band(120))
        assertEquals(yellow, band(200))
        assertEquals(red, band(300))
        // 65 displays as "65" or "3.6" but is a warning band in both -- the band
        // reads the raw mg/dL value, never the formatted one.
        assertEquals("65", GlucoseDisplayUtils.formatGlucose(65, GlucoseUnit.MGDL))
        assertEquals("3.6", GlucoseDisplayUtils.formatGlucose(65, GlucoseUnit.MMOL))
        assertEquals(yellow, band(65))
    }

    @Test
    fun `formatGlucose mmol uses a dot decimal under a comma-decimal locale`() {
        val original = Locale.getDefault()
        try {
            Locale.setDefault(Locale.GERMANY)
            assertEquals("6.7", GlucoseDisplayUtils.formatGlucose(120, GlucoseUnit.MMOL))
        } finally {
            Locale.setDefault(original)
        }
    }

    @Test
    fun `unitLabel returns the user-facing label`() {
        assertEquals("mg/dL", GlucoseDisplayUtils.unitLabel(GlucoseUnit.MGDL))
        assertEquals("mmol/L", GlucoseDisplayUtils.unitLabel(GlucoseUnit.MMOL))
    }

    @Test
    fun `formatWithLabel appends the unit label`() {
        assertEquals("120 mg/dL", GlucoseDisplayUtils.formatWithLabel(120, GlucoseUnit.MGDL))
        assertEquals("6.7 mmol/L", GlucoseDisplayUtils.formatWithLabel(120, GlucoseUnit.MMOL))
    }
}
