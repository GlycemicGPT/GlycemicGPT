package com.glycemicgpt.weardevice.util

import android.graphics.Color
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
}
