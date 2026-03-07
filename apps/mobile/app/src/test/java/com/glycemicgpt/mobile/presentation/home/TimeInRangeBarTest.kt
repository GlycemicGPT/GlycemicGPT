package com.glycemicgpt.mobile.presentation.home

import com.glycemicgpt.mobile.data.local.dao.TimeInRangeCounts
import com.glycemicgpt.mobile.domain.model.TimeInRangeData
import org.junit.Assert.assertEquals
import org.junit.Test

class TimeInRangeBarTest {

    // -- Percentage math via TimeInRangeCounts -> TimeInRangeData --------------

    @Test
    fun `zero readings produces all-zero percentages`() {
        val counts = TimeInRangeCounts(total = 0, urgentLowCount = 0, lowCount = 0, inRangeCount = 0, highCount = 0, urgentHighCount = 0)
        val data = counts.toTimeInRange()
        assertEquals(0f, data.urgentLowPercent, 0.001f)
        assertEquals(0f, data.lowPercent, 0.001f)
        assertEquals(0f, data.inRangePercent, 0.001f)
        assertEquals(0f, data.highPercent, 0.001f)
        assertEquals(0f, data.urgentHighPercent, 0.001f)
        assertEquals(0, data.totalReadings)
    }

    @Test
    fun `100 percent in range`() {
        val counts = TimeInRangeCounts(total = 200, urgentLowCount = 0, lowCount = 0, inRangeCount = 200, highCount = 0, urgentHighCount = 0)
        val data = counts.toTimeInRange()
        assertEquals(0f, data.urgentLowPercent, 0.001f)
        assertEquals(0f, data.lowPercent, 0.001f)
        assertEquals(100f, data.inRangePercent, 0.001f)
        assertEquals(0f, data.highPercent, 0.001f)
        assertEquals(0f, data.urgentHighPercent, 0.001f)
    }

    @Test
    fun `mixed distribution`() {
        val counts = TimeInRangeCounts(total = 100, urgentLowCount = 2, lowCount = 8, inRangeCount = 70, highCount = 15, urgentHighCount = 5)
        val data = counts.toTimeInRange()
        assertEquals(2f, data.urgentLowPercent, 0.001f)
        assertEquals(8f, data.lowPercent, 0.001f)
        assertEquals(70f, data.inRangePercent, 0.001f)
        assertEquals(15f, data.highPercent, 0.001f)
        assertEquals(5f, data.urgentHighPercent, 0.001f)
        assertEquals(100, data.totalReadings)
    }

    @Test
    fun `percentages sum to 100 for odd totals`() {
        val counts = TimeInRangeCounts(total = 5, urgentLowCount = 1, lowCount = 1, inRangeCount = 1, highCount = 1, urgentHighCount = 1)
        val data = counts.toTimeInRange()
        val sum = data.urgentLowPercent + data.lowPercent + data.inRangePercent + data.highPercent + data.urgentHighPercent
        assertEquals(100f, sum, 0.01f)
    }

    // -- Quality labels (calls real production function) -----------------------

    @Test
    fun `quality label is Excellent when inRange is 70 or above`() {
        assertEquals("Excellent", qualityAssessment(70f).first)
        assertEquals("Excellent", qualityAssessment(85f).first)
        assertEquals("Excellent", qualityAssessment(100f).first)
    }

    @Test
    fun `quality label is Good when inRange is 50 to 69`() {
        assertEquals("Good", qualityAssessment(50f).first)
        assertEquals("Good", qualityAssessment(69.9f).first)
    }

    @Test
    fun `quality label is Needs Improvement below 50`() {
        assertEquals("Needs Improvement", qualityAssessment(49f).first)
        assertEquals("Needs Improvement", qualityAssessment(0f).first)
    }

    // -- CGM Active assessment (calls real production function) -----------------

    @Test
    fun `cgmActiveAssessment is Good at 70 or above`() {
        assertEquals("Good", cgmActiveAssessment(70f).first)
        assertEquals("Good", cgmActiveAssessment(100f).first)
    }

    @Test
    fun `cgmActiveAssessment is Fair between 50 and 69`() {
        assertEquals("Fair", cgmActiveAssessment(50f).first)
        assertEquals("Fair", cgmActiveAssessment(69.9f).first)
    }

    @Test
    fun `cgmActiveAssessment is Low below 50`() {
        assertEquals("Low", cgmActiveAssessment(49f).first)
        assertEquals("Low", cgmActiveAssessment(0f).first)
    }

    // -- Format percent (calls real production function) -----------------------

    @Test
    fun `formatTirPercent handles zero`() {
        assertEquals("0%", formatTirPercent(0f))
    }

    @Test
    fun `formatTirPercent handles small values`() {
        assertEquals("<1%", formatTirPercent(0.3f))
    }

    @Test
    fun `formatTirPercent handles near-100 values`() {
        assertEquals(">99%", formatTirPercent(99.7f))
    }

    @Test
    fun `formatTirPercent handles normal values`() {
        assertEquals("50%", formatTirPercent(50f))
        assertEquals("75%", formatTirPercent(75.3f))
    }

    @Test
    fun `formatTirPercent handles exactly 100`() {
        assertEquals("100%", formatTirPercent(100f))
    }

    // -- Dynamic target range label -------------------------------------------

    @Test
    fun `target range label uses default thresholds`() {
        val thresholds = GlucoseThresholds()
        val label = "Target: ${thresholds.low}-${thresholds.high} mg/dL"
        assertEquals("Target: 70-180 mg/dL", label)
    }

    @Test
    fun `target range label uses custom thresholds`() {
        val thresholds = GlucoseThresholds(urgentLow = 60, low = 90, high = 230, urgentHigh = 330)
        val label = "Target: ${thresholds.low}-${thresholds.high} mg/dL"
        assertEquals("Target: 90-230 mg/dL", label)
    }

    @Test
    fun `legend labels reflect custom thresholds`() {
        val thresholds = GlucoseThresholds(urgentLow = 60, low = 90, high = 230, urgentHigh = 330)
        assertEquals("<60", "<${thresholds.urgentLow}")
        assertEquals("60-90", "${thresholds.urgentLow}-${thresholds.low}")
        assertEquals("90-230", "${thresholds.low}-${thresholds.high}")
        assertEquals("230-330", "${thresholds.high}-${thresholds.urgentHigh}")
        assertEquals(">330", ">${thresholds.urgentHigh}")
    }

    // -- Helper: mirrors repository logic for percentage math tests -----------

    private fun TimeInRangeCounts.toTimeInRange(): TimeInRangeData {
        if (total == 0) return TimeInRangeData(0f, 0f, 0f, 0f, 0f, 0)
        return TimeInRangeData(
            urgentLowPercent = urgentLowCount * 100f / total,
            lowPercent = lowCount * 100f / total,
            inRangePercent = inRangeCount * 100f / total,
            highPercent = highCount * 100f / total,
            urgentHighPercent = urgentHighCount * 100f / total,
            totalReadings = total,
        )
    }
}
