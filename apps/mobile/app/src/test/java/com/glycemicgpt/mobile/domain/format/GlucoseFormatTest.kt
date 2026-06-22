package com.glycemicgpt.mobile.domain.format

import com.glycemicgpt.mobile.domain.model.GlucoseUnit
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.After
import org.junit.Test
import java.util.Locale

/**
 * Tests for the single client-side glucose formatter. The clinical anchors
 * (70 -> 3.9, 180 -> 10.0, 120 -> 6.7, 100 -> 5.6) are the load-bearing cases:
 * they pin the conversion constant and the round-LAST rule, and must match the
 * backend / web rendering of the same stored mg/dL values.
 */
class GlucoseFormatTest {

    @After
    fun restoreLocale() {
        Locale.setDefault(savedLocale)
    }

    private val savedLocale: Locale = Locale.getDefault()

    @Test
    fun `constant is the single canonical factor`() {
        assertEquals(18.0156, GlucoseFormat.MGDL_PER_MMOL, 0.0)
    }

    @Test
    fun `mgdl value formats as integer with no conversion`() {
        assertEquals("120", GlucoseFormat.format(120, GlucoseUnit.MGDL))
        assertEquals("70", GlucoseFormat.format(70, GlucoseUnit.MGDL))
        assertEquals("250", GlucoseFormat.format(250, GlucoseUnit.MGDL))
    }

    @Test
    fun `mmol value renders the clinical anchors`() {
        assertEquals("3.9", GlucoseFormat.format(70, GlucoseUnit.MMOL))
        assertEquals("10.0", GlucoseFormat.format(180, GlucoseUnit.MMOL))
        assertEquals("6.7", GlucoseFormat.format(120, GlucoseUnit.MMOL))
        assertEquals("5.6", GlucoseFormat.format(100, GlucoseUnit.MMOL))
    }

    @Test
    fun `formatWithLabel pairs value and unit label`() {
        assertEquals("120 mg/dL", GlucoseFormat.formatWithLabel(120, GlucoseUnit.MGDL))
        assertEquals("6.7 mmol/L", GlucoseFormat.formatWithLabel(120, GlucoseUnit.MMOL))
    }

    @Test
    fun `labels and spoken units are unit-correct`() {
        assertEquals("mg/dL", GlucoseFormat.label(GlucoseUnit.MGDL))
        assertEquals("mmol/L", GlucoseFormat.label(GlucoseUnit.MMOL))
        assertEquals("milligrams per deciliter", GlucoseFormat.spokenUnit(GlucoseUnit.MGDL))
        assertEquals("millimoles per liter", GlucoseFormat.spokenUnit(GlucoseUnit.MMOL))
    }

    @Test
    fun `convertValue divides by the factor for mmol and is identity for mgdl`() {
        assertEquals(120.0, GlucoseFormat.convertValue(120, GlucoseUnit.MGDL), 0.0)
        assertEquals(120 / 18.0156, GlucoseFormat.convertValue(120, GlucoseUnit.MMOL), 1e-9)
    }

    @Test
    fun `convertSpread is offset-free divide-by-factor`() {
        // A spread of 18.0156 mg/dL is exactly 1.0 mmol/L -- no anchor, no offset.
        assertEquals(1.0, GlucoseFormat.convertSpread(18.0156), 1e-9)
        assertEquals(0.0, GlucoseFormat.convertSpread(0.0), 0.0)
    }

    @Test
    fun `mean formats as integer for mgdl and one decimal for mmol`() {
        assertEquals("117", GlucoseFormat.formatMean(117.4f, GlucoseUnit.MGDL))
        assertEquals("6.5", GlucoseFormat.formatMean(117.4f, GlucoseUnit.MMOL))
    }

    @Test
    fun `std-dev formats one decimal in either unit via the spread converter`() {
        assertEquals("23.4", GlucoseFormat.formatSpread(23.42f, GlucoseUnit.MGDL))
        // 36 mg/dL spread -> 36 / 18.0156 = 1.998 -> 2.0 mmol/L
        assertEquals("2.0", GlucoseFormat.formatSpread(36f, GlucoseUnit.MMOL))
    }

    @Test
    fun `round-trips through mmol stay within one display step`() {
        // Rounding mmol to 1 dp introduces at most 0.05 mmol/L of error, i.e. ~0.9 mg/dL when
        // converted back. A looser bound would let a real conversion bug slip through.
        val maxDriftMgDl = 0.05 * GlucoseFormat.MGDL_PER_MMOL + 1e-6
        for (mgDl in 40..400 step 1) {
            val mmol = GlucoseFormat.format(mgDl, GlucoseUnit.MMOL).toDouble()
            val backToMgDl = mmol * GlucoseFormat.MGDL_PER_MMOL
            assertTrue(
                "round-trip for $mgDl mg/dL drifted too far: $mmol mmol/L -> $backToMgDl",
                kotlin.math.abs(backToMgDl - mgDl) <= maxDriftMgDl,
            )
        }
    }

    @Test
    fun `mmol uses a dot separator regardless of device locale`() {
        // A comma-decimal locale (e.g. Germany) must NOT produce "5,6" -- the log
        // scrubber and cross-surface consistency both require a dot.
        Locale.setDefault(Locale.GERMANY)
        assertEquals("5.6", GlucoseFormat.format(100, GlucoseUnit.MMOL))
        assertEquals("6.7 mmol/L", GlucoseFormat.formatWithLabel(120, GlucoseUnit.MMOL))
        assertEquals("6.5", GlucoseFormat.formatMean(117.4f, GlucoseUnit.MMOL))
    }

    @Test
    fun `boundary values format cleanly`() {
        assertEquals("1.1", GlucoseFormat.format(20, GlucoseUnit.MMOL))
        assertEquals("27.8", GlucoseFormat.format(500, GlucoseUnit.MMOL))
        assertEquals("20", GlucoseFormat.format(20, GlucoseUnit.MGDL))
        assertEquals("500", GlucoseFormat.format(500, GlucoseUnit.MGDL))
    }
}
