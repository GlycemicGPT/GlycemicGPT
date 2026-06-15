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
    fun `the verify-before-dosing qualifier text mentions both estimate and dosing`() {
        assertTrue(VERIFY_BEFORE_DOSING_TEXT.contains("Estimate", ignoreCase = true))
        assertTrue(VERIFY_BEFORE_DOSING_TEXT.contains("dosing", ignoreCase = true))
    }
}
