package com.glycemicgpt.mobile.domain.compute

import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.BolusType
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.model.PumpActivityMode
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant
import java.time.ZoneId

class DashboardComputationsTest {

    private fun cgm(glucoseMgDl: Int, hoursAgo: Long = 0, minutesAgo: Long = 0): CgmReading {
        val ts = Instant.now().minusSeconds(hoursAgo * 3600 + minutesAgo * 60)
        return CgmReading(glucoseMgDl = glucoseMgDl, trendArrow = CgmTrend.FLAT, timestamp = ts)
    }

    private fun cgmAtHour(glucoseMgDl: Int, hour: Int): CgmReading {
        val today = Instant.now().atZone(ZoneId.systemDefault())
            .withHour(hour).withMinute(0).withSecond(0).toInstant()
        return CgmReading(glucoseMgDl = glucoseMgDl, trendArrow = CgmTrend.FLAT, timestamp = today)
    }

    private fun basal(rate: Float, hoursAgo: Long): BasalReading {
        val ts = Instant.now().minusSeconds(hoursAgo * 3600)
        return BasalReading(
            rate = rate,
            isAutomated = true,
            activityMode = PumpActivityMode.NONE,
            timestamp = ts,
        )
    }

    private fun bolus(units: Float, minutesAgo: Long, isAutomated: Boolean = false, isCorrection: Boolean = false): BolusEvent {
        val ts = Instant.now().minusSeconds(minutesAgo * 60)
        return BolusEvent(
            units = units,
            isAutomated = isAutomated,
            isCorrection = isCorrection,
            timestamp = ts,
        )
    }

    private fun iob(iob: Float, minutesAgo: Long): IoBReading {
        val ts = Instant.now().minusSeconds(minutesAgo * 60)
        return IoBReading(iob = iob, timestamp = ts)
    }

    // -- computeAgp -----------------------------------------------------------

    @Test
    fun `computeAgp returns null for empty readings`() {
        assertNull(DashboardComputations.computeAgp(emptyList(), 14))
    }

    @Test
    fun `computeAgp returns null for insufficient readings`() {
        val readings = (1..100).map { cgm(120, minutesAgo = it.toLong() * 5) }
        assertNull(DashboardComputations.computeAgp(readings, 14))
    }

    @Test
    fun `computeAgp returns profile with 24 buckets for sufficient data`() {
        // Generate 1000 readings spread across multiple hours
        val readings = (0 until 1000).map { i ->
            cgm(100 + (i % 50), minutesAgo = i.toLong() * 5)
        }
        val profile = DashboardComputations.computeAgp(readings, 7)
        assertNotNull(profile)
        assertEquals(24, profile!!.buckets.size)
        assertEquals(1000, profile.totalReadings)
        assertEquals(7, profile.periodDays)
    }

    @Test
    fun `computeAgp buckets have ordered percentiles`() {
        val readings = (0 until 1000).map { i ->
            cgm(80 + (i % 100), minutesAgo = i.toLong() * 5)
        }
        val profile = DashboardComputations.computeAgp(readings, 7)!!
        for (bucket in profile.buckets) {
            if (bucket.count > 1) {
                assertTrue("p10 <= p25", bucket.p10 <= bucket.p25)
                assertTrue("p25 <= p50", bucket.p25 <= bucket.p50)
                assertTrue("p50 <= p75", bucket.p50 <= bucket.p75)
                assertTrue("p75 <= p90", bucket.p75 <= bucket.p90)
            }
        }
    }

    // -- computeCgmStats ------------------------------------------------------

    @Test
    fun `computeCgmStats returns null for empty readings`() {
        assertNull(DashboardComputations.computeCgmStats(emptyList()))
    }

    @Test
    fun `computeCgmStats computes correct mean`() {
        val readings = listOf(cgm(100), cgm(200))
        val stats = DashboardComputations.computeCgmStats(readings)!!
        assertEquals(150f, stats.meanGlucose, 0.01f)
        assertEquals(2, stats.readingsCount)
    }

    @Test
    fun `computeCgmStats computes correct CV and GMI`() {
        // All same value -> stdDev=0, CV=0
        val readings = listOf(cgm(120), cgm(120), cgm(120))
        val stats = DashboardComputations.computeCgmStats(readings)!!
        assertEquals(120f, stats.meanGlucose, 0.01f)
        assertEquals(0f, stats.stdDev, 0.01f)
        assertEquals(0f, stats.cvPercent, 0.01f)
        // GMI = 3.31 + 0.02392 * 120 = 6.18
        assertEquals(6.18f, stats.gmi, 0.01f)
    }

    @Test
    fun `computeCgmStats computes non-zero stdDev`() {
        val readings = listOf(cgm(100), cgm(200), cgm(150))
        val stats = DashboardComputations.computeCgmStats(readings)!!
        assertTrue(stats.stdDev > 0f)
        assertTrue(stats.cvPercent > 0f)
    }

    // -- computeInsulinSummary ------------------------------------------------

    @Test
    fun `computeInsulinSummary returns null for zero insulin`() {
        assertNull(DashboardComputations.computeInsulinSummary(emptyList(), emptyList(), 24))
    }

    @Test
    fun `computeInsulinSummary bolus only`() {
        val boluses = listOf(bolus(5f, 60), bolus(3f, 120))
        val summary = DashboardComputations.computeInsulinSummary(emptyList(), boluses, 24)!!
        assertEquals(8f, summary.totalDailyDose, 0.01f)
        assertEquals(0f, summary.basalUnits, 0.01f)
        assertEquals(8f, summary.bolusUnits, 0.01f)
        assertEquals(0f, summary.basalPercent, 0.01f)
        assertEquals(100f, summary.bolusPercent, 0.01f)
    }

    @Test
    fun `computeInsulinSummary basal integral`() {
        // 1 U/hr for 2 hours = 2U basal
        val basals = listOf(basal(1.0f, 2), basal(1.0f, 0))
        val summary = DashboardComputations.computeInsulinSummary(basals, emptyList(), 24)!!
        assertEquals(2f, summary.basalUnits * 1, 0.1f) // TDD = total/days, days=1
        assertTrue(summary.basalPercent > 0f)
    }

    @Test
    fun `computeInsulinSummary multi-day averaging`() {
        val boluses = listOf(bolus(10f, 60))
        // 48 hours = 2 days
        val summary = DashboardComputations.computeInsulinSummary(emptyList(), boluses, 48)!!
        assertEquals(5f, summary.totalDailyDose, 0.01f) // 10U / 2 days
    }

    // -- enrichBoluses --------------------------------------------------------

    @Test
    fun `enrichBoluses returns empty for no boluses`() {
        assertTrue(DashboardComputations.enrichBoluses(emptyList(), emptyList(), emptyList()).isEmpty())
    }

    @Test
    fun `enrichBoluses cross-references CGM within window`() {
        val b = bolus(2f, 10)
        val c = cgm(150, minutesAgo = 10) // Same timestamp
        val i = iob(3.5f, 10) // Same timestamp
        val result = DashboardComputations.enrichBoluses(listOf(b), listOf(c), listOf(i))
        assertEquals(1, result.size)
        assertEquals(150, result[0].bgAtEvent)
        assertEquals(3.5f, result[0].iobAtEvent!!, 0.01f)
    }

    @Test
    fun `enrichBoluses returns null BG when no CGM within window`() {
        val b = bolus(2f, 10)
        val c = cgm(150, minutesAgo = 20) // 10 minutes apart > 5-minute window
        val result = DashboardComputations.enrichBoluses(listOf(b), listOf(c), emptyList())
        assertEquals(1, result.size)
        assertNull(result[0].bgAtEvent)
        assertNull(result[0].iobAtEvent)
    }

    @Test
    fun `enrichBoluses handles boundary of 5-minute window`() {
        // Exactly 5 minutes = 300,000 ms -- should be within window
        val bolusTime = Instant.now()
        val b = BolusEvent(units = 2f, isAutomated = false, isCorrection = false, timestamp = bolusTime)
        val cgmJustInside = CgmReading(
            glucoseMgDl = 150,
            trendArrow = CgmTrend.FLAT,
            timestamp = bolusTime.minusSeconds(299), // 4:59 before
        )
        val result = DashboardComputations.enrichBoluses(listOf(b), listOf(cgmJustInside), emptyList())
        assertEquals(150, result[0].bgAtEvent)
    }

    @Test
    fun `enrichBoluses handles multiple boluses at same timestamp`() {
        val ts = Instant.now()
        val b1 = BolusEvent(units = 2f, isAutomated = false, isCorrection = false, timestamp = ts)
        val b2 = BolusEvent(units = 0.5f, isAutomated = true, isCorrection = true, timestamp = ts)
        val c = CgmReading(glucoseMgDl = 130, trendArrow = CgmTrend.FLAT, timestamp = ts)
        val result = DashboardComputations.enrichBoluses(listOf(b1, b2), listOf(c), emptyList())
        assertEquals(2, result.size)
        assertEquals(130, result[0].bgAtEvent)
        assertEquals(130, result[1].bgAtEvent)
    }

    @Test
    fun `enrichBoluses derives correct bolus type`() {
        val autoCorr = bolus(0.5f, 10, isAutomated = true, isCorrection = true)
        val corr = bolus(1f, 20, isAutomated = false, isCorrection = true)
        val meal = bolus(3f, 30, isAutomated = false, isCorrection = false)
        val auto = bolus(0.3f, 40, isAutomated = true, isCorrection = false)

        val result = DashboardComputations.enrichBoluses(
            listOf(autoCorr, corr, meal, auto),
            emptyList(),
            emptyList(),
        )
        assertEquals(BolusType.AUTO_CORRECTION, result[0].bolusType)
        assertEquals(BolusType.CORRECTION, result[1].bolusType)
        assertEquals(BolusType.MEAL, result[2].bolusType)
        assertEquals(BolusType.AUTO, result[3].bolusType)
    }

    // -- percentile -----------------------------------------------------------

    @Test
    fun `percentile returns correct values for simple list`() {
        val sorted = listOf(10f, 20f, 30f, 40f, 50f)
        assertEquals(10f, DashboardComputations.percentile(sorted, 0f), 0.01f)
        assertEquals(30f, DashboardComputations.percentile(sorted, 50f), 0.01f)
        assertEquals(50f, DashboardComputations.percentile(sorted, 100f), 0.01f)
    }

    @Test
    fun `percentile returns 0 for empty list`() {
        assertEquals(0f, DashboardComputations.percentile(emptyList(), 50f), 0.01f)
    }

    @Test
    fun `percentile returns single value for single-element list`() {
        assertEquals(42f, DashboardComputations.percentile(listOf(42f), 50f), 0.01f)
    }

    // -- computeBasalIntegral -------------------------------------------------

    @Test
    fun `computeBasalIntegral returns 0 for empty list`() {
        assertEquals(0f, DashboardComputations.computeBasalIntegral(emptyList()), 0.01f)
    }

    @Test
    fun `computeBasalIntegral caps segments at 2 hours`() {
        // Two readings 10 hours apart at 1 U/hr -> first segment capped to 2U
        // Second segment extends to now (0 hours ago to now = ~0U)
        val basals = listOf(basal(1.0f, 10), basal(1.0f, 0))
        val result = DashboardComputations.computeBasalIntegral(basals)
        // First segment: 10h gap capped to 2h = 2U, second segment: ~0h to now = ~0U
        assertEquals(2f, result, 0.1f)
    }

    @Test
    fun `computeBasalIntegral includes last segment to now`() {
        // Single reading 1 hour ago at 2 U/hr -> extends to now = ~2U
        val basals = listOf(basal(2.0f, 1))
        val result = DashboardComputations.computeBasalIntegral(basals)
        assertEquals(2f, result, 0.1f)
    }
}
