package com.glycemicgpt.mobile.presentation.home

import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.model.GlucoseUnit
import com.glycemicgpt.mobile.domain.format.GlucoseFormat
import com.glycemicgpt.mobile.presentation.theme.GlucoseColors
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Phone glucose band + trend-arrow regressions for the unit epic.
 *
 * Both [glucoseColor] and [trendArrowSymbol] take a stored mg/dL value or a CGM
 * trend and NO display unit -- the user's mg/dL vs mmol/L preference can never
 * reach them. These tests pin that: the severity color a reading shows, and the
 * trend arrow shown beside it, are identical whether the number is displayed as
 * 65 or 3.6. [GlucoseFormat] (the unit-aware formatter) is exercised here only
 * to prove the displayed string genuinely differs while the band does not.
 *
 * Note: the theme collapses the low and high warning bands to one color
 * (Yellow500) and the two urgent bands to one (Red500), so a Color assertion
 * pins the severity a reading shows, not the low-vs-high name. That severity is
 * exactly what the cross-surface contract needs -- a reading must show the same
 * severity on the phone, web, and watch. The boundary test below pins the
 * comparison operators so a band can never silently slip by one mg/dL.
 */
class GlucoseHeroTest {

    // Values chosen to land in the SAME band on the phone, web (classifyGlucose),
    // and watch (bgColor); threshold edges are avoided here because the surfaces
    // differ by one mg/dL at the boundary.
    @Test
    fun `glucoseColor bands the stored mg-dL value, never the displayed one`() {
        assertEquals(GlucoseColors.UrgentLow, glucoseColor(40))
        assertEquals(GlucoseColors.Low, glucoseColor(65))
        assertEquals(GlucoseColors.InRange, glucoseColor(120))
        assertEquals(GlucoseColors.High, glucoseColor(200))
        assertEquals(GlucoseColors.UrgentHigh, glucoseColor(300))
    }

    @Test
    fun `glucoseColor switches severity exactly at each default threshold`() {
        // Each transition crosses a DISTINCT color (red->yellow->green->yellow->
        // red), so these catch an off-by-one or inverted comparison in the band
        // boundaries (defaults 55 / 70 / 180 / 250).
        assertEquals(GlucoseColors.UrgentLow, glucoseColor(55))
        assertEquals(GlucoseColors.Low, glucoseColor(56))
        assertEquals(GlucoseColors.Low, glucoseColor(70))
        assertEquals(GlucoseColors.InRange, glucoseColor(71))
        assertEquals(GlucoseColors.InRange, glucoseColor(179))
        assertEquals(GlucoseColors.High, glucoseColor(180))
        assertEquals(GlucoseColors.High, glucoseColor(249))
        assertEquals(GlucoseColors.UrgentHigh, glucoseColor(250))
    }

    @Test
    fun `a low reading stays low even though its displayed number changes with unit`() {
        // 65 mg/dL shows as "65" or "3.6"; it is a warning (Low) reading in both,
        // because the band reads the raw mg/dL value, not the formatted string.
        assertEquals("65", GlucoseFormat.format(65, GlucoseUnit.MGDL))
        assertEquals("3.6", GlucoseFormat.format(65, GlucoseUnit.MMOL))
        assertEquals(GlucoseColors.Low, glucoseColor(65))
    }

    @Test
    fun `trendArrowSymbol is a pure function of the trend with no unit input`() {
        // The arrow is derived from the backend trend direction alone; there is
        // no unit parameter, so switching units can never flip it.
        assertEquals("⇈", trendArrowSymbol(CgmTrend.DOUBLE_UP))
        assertEquals("↑", trendArrowSymbol(CgmTrend.SINGLE_UP))
        assertEquals("↗", trendArrowSymbol(CgmTrend.FORTY_FIVE_UP))
        assertEquals("→", trendArrowSymbol(CgmTrend.FLAT))
        assertEquals("↘", trendArrowSymbol(CgmTrend.FORTY_FIVE_DOWN))
        assertEquals("↓", trendArrowSymbol(CgmTrend.SINGLE_DOWN))
        assertEquals("⇊", trendArrowSymbol(CgmTrend.DOUBLE_DOWN))
        assertEquals("?", trendArrowSymbol(CgmTrend.UNKNOWN))
    }
}
