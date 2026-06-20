package com.glycemicgpt.mobile.presentation.meal

import com.glycemicgpt.mobile.data.meal.CarbConfidence
import com.glycemicgpt.mobile.data.meal.CarbRange
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Guards the carb-display invariants behind the safety posture: an estimate is always shown as a
 * range with units and an accompanying confidence label, never a bare/lone integer.
 */
class MealComponentsTest {

    @Test
    fun `a range renders low to high with units`() {
        assertEquals("≈ 40–55 g carbs", formatCarbRange(CarbRange(40.0, 55.0)))
    }

    @Test
    fun `a single-point estimate still renders with units, never a bare number`() {
        val formatted = formatCarbRange(CarbRange(50.0, 50.0))
        assertEquals("≈ 50 g carbs", formatted)
        assertTrue("must carry units, not a lone integer", formatted.contains("g carbs"))
    }

    @Test
    fun `fractional grams keep one decimal`() {
        assertEquals("≈ 12.5–20 g carbs", formatCarbRange(CarbRange(12.5, 20.0)))
    }

    @Test
    fun `every confidence level has a non-empty label, including unknown`() {
        CarbConfidence.entries.forEach { level ->
            assertTrue(
                "confidence $level must have a visible label",
                confidenceLabel(level).isNotBlank(),
            )
        }
        assertEquals("Confidence unavailable", confidenceLabel(CarbConfidence.UNKNOWN))
    }

    @Test
    fun `editable grams drops a trailing zero decimal`() {
        assertEquals("40", formatEditableGrams(40.0))
        assertEquals("12.5", formatEditableGrams(12.5))
    }

    @Test
    fun `the qualifier text names that it is a guess and forbids dosing`() {
        assertTrue(VERIFY_BEFORE_DOSING_TEXT.contains("estimate", ignoreCase = true))
        // Story 50.S: must name the prohibited action explicitly, not just "verify".
        assertTrue(VERIFY_BEFORE_DOSING_TEXT.contains("insulin dose", ignoreCase = true))
        assertTrue(VERIFY_BEFORE_DOSING_TEXT.contains("bolus", ignoreCase = true))
    }

    @Test
    fun `net carbs renders as a g range, never bare`() {
        // Story 50.N1: mirrors the carb range -- a band with units, single value
        // when the rounded endpoints coincide.
        assertEquals("≈ 34–49 g", formatNetCarbs(34.0, 49.0))
        assertEquals("≈ 26 g", formatNetCarbs(26.0, 26.0))
    }

    @Test
    fun `net carbs round to whole grams, matching the web client (no false precision)`() {
        // A fractional server value must render in whole grams on both clients;
        // 33.6 and 34.4 both round to 34, collapsing the band.
        assertEquals("≈ 34 g", formatNetCarbs(33.6, 34.4))
        assertEquals("≈ 12–14 g", formatNetCarbs(12.4, 13.6))
    }
}
