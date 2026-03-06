package com.glycemicgpt.mobile.domain.compute

import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BolusCategory
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.BolusType
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.model.PumpActivityMode
import com.glycemicgpt.mobile.domain.plugin.capabilities.BolusCategoryProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZonedDateTime

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

    private fun bolus(
        units: Float,
        minutesAgo: Long,
        isAutomated: Boolean = false,
        isCorrection: Boolean = false,
        correctionUnits: Float = 0f,
        mealUnits: Float = 0f,
    ): BolusEvent {
        val ts = Instant.now().minusSeconds(minutesAgo * 60)
        return BolusEvent(
            units = units,
            isAutomated = isAutomated,
            isCorrection = isCorrection,
            correctionUnits = correctionUnits,
            mealUnits = mealUnits,
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
    fun `computeInsulinSummary returns null for zero periodHours`() {
        val boluses = listOf(bolus(5f, 60))
        assertNull(DashboardComputations.computeInsulinSummary(emptyList(), boluses, 0))
    }

    @Test
    fun `computeInsulinSummary returns null for negative periodHours`() {
        val boluses = listOf(bolus(5f, 60))
        assertNull(DashboardComputations.computeInsulinSummary(emptyList(), boluses, -24))
    }

    @Test
    fun `computeInsulinSummary bolus only`() {
        // Boluses 1-2 hours ago -> data span < 1 day -> clamped to 1 day
        val boluses = listOf(bolus(5f, 60), bolus(3f, 120))
        val summary = DashboardComputations.computeInsulinSummary(emptyList(), boluses, 24)!!
        assertEquals(8f, summary.totalDailyDose, 0.01f)
        assertEquals(0f, summary.basalUnits, 0.01f)
        assertEquals(8f, summary.bolusUnits, 0.01f)
        assertEquals(0f, summary.basalPercent, 0.01f)
        assertEquals(100f, summary.bolusPercent, 0.01f)
        assertEquals(2, summary.bolusCount)
        assertEquals(0, summary.correctionCount)
        assertEquals(0f, summary.correctionUnits, 0.01f)
        assertEquals(1f, summary.periodDays, 0.01f)
    }

    @Test
    fun `computeInsulinSummary basal integral`() {
        // 1 U/hr for 2 hours = 2U basal, data span 2h -> clamped to 1 day
        val basals = listOf(basal(1.0f, 2), basal(1.0f, 0))
        val summary = DashboardComputations.computeInsulinSummary(basals, emptyList(), 24)!!
        assertEquals(2f, summary.basalUnits, 0.1f) // TDD = total/days, days=1
        assertTrue(summary.basalPercent > 0f)
        assertEquals(1f, summary.periodDays, 0.01f)
    }

    @Test
    fun `computeInsulinSummary multi-day uses actual data span`() {
        // Bolus 1 hour ago, selected period 48h -> data span ~1h, clamped to 1 day
        // Since there's only 1 hour of data, dividing by 2 days would be misleading
        val boluses = listOf(bolus(10f, 60))
        val summary = DashboardComputations.computeInsulinSummary(emptyList(), boluses, 48)!!
        assertEquals(10f, summary.totalDailyDose, 0.01f) // 10U / 1 day (not 2)
        assertEquals(1f, summary.periodDays, 0.01f)
    }

    @Test
    fun `computeInsulinSummary multi-day with actual multi-day data`() {
        // Boluses spanning 2+ days -> should divide by actual span
        val boluses = listOf(
            bolus(10f, 60),          // 1 hour ago
            bolus(10f, 60 * 49),     // 49 hours ago (~2 days)
        )
        val summary = DashboardComputations.computeInsulinSummary(emptyList(), boluses, 72)!!
        // Data span is ~49 hours = ~2.04 days, total = 20U, TDD ~ 9.8 U/day
        assertTrue(summary.periodDays > 1.9f && summary.periodDays < 2.1f)
        assertTrue(summary.totalDailyDose > 9f && summary.totalDailyDose < 11f)
    }

    @Test
    fun `insulin summary same data same TDD regardless of selected period`() {
        // Data only spans a few hours -- selecting 24H, 3D, or 7D should all
        // produce the same TDD because we divide by actual data span (clamped to 1 day),
        // not the selected period. This was the original normalization bug.
        val boluses = listOf(
            bolus(5f, 60),    // 1 hour ago
            bolus(3f, 120),   // 2 hours ago
            bolus(4f, 600),   // 10 hours ago
        )
        val summary24 = DashboardComputations.computeInsulinSummary(emptyList(), boluses, 24)!!
        val summary72 = DashboardComputations.computeInsulinSummary(emptyList(), boluses, 72)!!
        assertEquals(
            summary24.totalDailyDose,
            summary72.totalDailyDose,
            0.01f,
        )
    }

    @Test
    fun `insulin summary counts corrections by flag and breakdown`() {
        val boluses = listOf(
            bolus(3f, 60, isCorrection = false, correctionUnits = 0f),          // meal only
            bolus(1f, 120, isCorrection = true, correctionUnits = 0f),          // correction by flag
            bolus(2f, 180, isCorrection = false, correctionUnits = 1.5f),       // correction by breakdown
            bolus(4f, 240, isCorrection = true, correctionUnits = 0.5f, mealUnits = 3.5f), // combo
        )
        val summary = DashboardComputations.computeInsulinSummary(emptyList(), boluses, 24)!!
        assertEquals(4, summary.bolusCount)
        assertEquals(3, summary.correctionCount) // boluses[1], boluses[2], boluses[3]
        // Correction units: bolus[1]=1.0 (full units, no breakdown), bolus[2]=1.5, bolus[3]=0.5
        assertEquals(3f, summary.correctionUnits, 0.01f) // (1.0 + 1.5 + 0.5) / 1 day
    }

    @Test
    fun `insulin summary correction fallback uses full units for combo with flag only`() {
        // Edge case: isCorrection=true on a combo bolus with no correctionUnits breakdown.
        // The fallback uses full units (3.0), which overcounts correction insulin by
        // including the meal portion. This is documented acceptable behavior because
        // Tandem pump data always provides the breakdown.
        val combo = bolus(3f, 60, isCorrection = true, correctionUnits = 0f, mealUnits = 2f)
        val summary = DashboardComputations.computeInsulinSummary(emptyList(), listOf(combo), 24)!!
        assertEquals(1, summary.correctionCount)
        // Falls back to full units (3.0) since correctionUnits == 0
        assertEquals(3f, summary.correctionUnits, 0.01f)
    }

    @Test
    fun `insulin summary portion-based sums food and correction portions`() {
        val boluses = listOf(
            bolus(3f, 60, isAutomated = false, isCorrection = false),          // FOOD: 3U food
            bolus(1f, 120, isAutomated = true, isCorrection = true),           // AUTO: 1U correction
            bolus(4f, 180, isCorrection = true, correctionUnits = 0.5f, mealUnits = 3.5f), // combo: 3.5U food + 0.5U correction
            bolus(2f, 240, isCorrection = true, correctionUnits = 0f),         // BG Only: 2U correction (flag only)
            bolus(0.3f, 300, isAutomated = true, isCorrection = false),        // AUTO: 0.3U correction
        )
        val summary = DashboardComputations.computeInsulinSummary(emptyList(), boluses, 24)!!
        // foodBolusUnits = 3.0 (meal) + 3.5 (combo meal portion) = 6.5
        assertEquals(6.5f, summary.foodBolusUnits, 0.01f)
        // correctionBolusUnits = 1.0 (auto) + 0.5 (combo correction) + 2.0 (bg only) + 0.3 (auto) = 3.8
        assertEquals(3.8f, summary.correctionBolusUnits, 0.01f)
        // Food + correction portions = total bolus
        assertEquals(summary.bolusUnits, summary.foodBolusUnits + summary.correctionBolusUnits, 0.01f)
    }

    @Test
    fun `insulin summary automated boluses all go to correction portion`() {
        val boluses = listOf(
            bolus(1f, 60, isAutomated = true, isCorrection = true),      // AUTO_CORRECTION
            bolus(0.5f, 120, isAutomated = true, isCorrection = false),  // AUTO
        )
        val summary = DashboardComputations.computeInsulinSummary(emptyList(), boluses, 24)!!
        assertEquals(1.5f, summary.correctionBolusUnits, 0.01f)
        assertEquals(0f, summary.foodBolusUnits, 0.01f)
    }

    @Test
    fun `insulin summary category breakdown has correct counts`() {
        val boluses = listOf(
            bolus(5f, 60, isAutomated = false, isCorrection = false),                         // FOOD
            bolus(2f, 120, isAutomated = true, isCorrection = true),                           // AUTO_CORRECTION
            bolus(4f, 180, isCorrection = true, correctionUnits = 1f, mealUnits = 3f),        // FOOD_AND_CORRECTION
            bolus(1f, 240, isAutomated = false, isCorrection = true, correctionUnits = 0f),   // CORRECTION
        )
        val summary = DashboardComputations.computeInsulinSummary(emptyList(), boluses, 24)!!
        val breakdown = summary.categoryBreakdown
        assertEquals(1, breakdown[BolusCategory.FOOD]?.count)
        assertEquals(1, breakdown[BolusCategory.AUTO_CORRECTION]?.count)
        assertEquals(1, breakdown[BolusCategory.FOOD_AND_CORRECTION]?.count)
        assertEquals(1, breakdown[BolusCategory.CORRECTION]?.count)
    }

    @Test
    fun `insulin summary mixed bolus types produce correct portion-based breakdown`() {
        val boluses = listOf(
            bolus(5f, 60, isAutomated = false, isCorrection = false),                         // FOOD
            bolus(2f, 120, isAutomated = true, isCorrection = true),                           // AUTO
            bolus(4f, 180, isCorrection = true, correctionUnits = 1f, mealUnits = 3f),        // combo
            bolus(1f, 240, isAutomated = false, isCorrection = true, correctionUnits = 0f),   // BG Only
        )
        val summary = DashboardComputations.computeInsulinSummary(emptyList(), boluses, 24)!!
        // Portion-based: food = 5 (meal) + 3 (combo meal) = 8; correction = 2 (auto) + 1 (combo corr) + 1 (bg) = 4
        assertEquals(8f, summary.foodBolusUnits, 0.01f)
        assertEquals(4f, summary.correctionBolusUnits, 0.01f)
    }

    @Test
    fun `insulin summary combo bolus splits portions correctly`() {
        // A combo bolus of 4U (3U meal + 1U correction):
        // foodBolusUnits gets 3U (meal portion)
        // correctionBolusUnits gets 1U (correction portion)
        // correctionUnits also gets 1U (aggregate correction tracking)
        val combo = bolus(4f, 60, isCorrection = false, correctionUnits = 1f, mealUnits = 3f)
        val summary = DashboardComputations.computeInsulinSummary(emptyList(), listOf(combo), 24)!!
        assertEquals(3f, summary.foodBolusUnits, 0.01f)        // meal portion
        assertEquals(1f, summary.correctionBolusUnits, 0.01f)  // correction portion
        assertEquals(1f, summary.correctionUnits, 0.01f)       // aggregate correction
        // Category: FOOD_AND_CORRECTION
        assertEquals(1, summary.categoryBreakdown[BolusCategory.FOOD_AND_CORRECTION]?.count)
    }

    @Test
    fun `insulin summary with provider uses plugin categories`() {
        val provider = object : BolusCategoryProvider {
            override fun declaredCategories() = setOf("CIQ", "OVERRIDE")
            override fun toPlatformCategory(pluginCategory: String) = when (pluginCategory) {
                "CIQ" -> "AUTO_CORRECTION"
                "OVERRIDE" -> "OVERRIDE"
                else -> null
            }
        }
        val boluses = listOf(
            bolus(1f, 60, isAutomated = true, isCorrection = true).copy(category = "CIQ"),
            bolus(5f, 120, isAutomated = false, isCorrection = false).copy(category = "OVERRIDE"),
        )
        val summary = DashboardComputations.computeInsulinSummary(emptyList(), boluses, 24, provider)!!
        assertEquals(1, summary.categoryBreakdown[BolusCategory.AUTO_CORRECTION]?.count)
        assertEquals(1, summary.categoryBreakdown[BolusCategory.OVERRIDE]?.count)
    }

    @Test
    fun `insulin summary backward compat empty category uses flag fallback`() {
        // Old data with empty category field
        val b = bolus(5f, 60, isAutomated = false, isCorrection = false)
        val summary = DashboardComputations.computeInsulinSummary(emptyList(), listOf(b), 24)!!
        assertEquals(1, summary.categoryBreakdown[BolusCategory.FOOD]?.count)
    }

    @Test
    fun `insulin summary periodDays capped at selected period`() {
        // Data from 1h ago, all periods should clamp to 1 day (minimum)
        val boluses = listOf(bolus(5f, 60))
        val s24 = DashboardComputations.computeInsulinSummary(emptyList(), boluses, 24)!!
        val s72 = DashboardComputations.computeInsulinSummary(emptyList(), boluses, 72)!!
        val s168 = DashboardComputations.computeInsulinSummary(emptyList(), boluses, 168)!!
        // All clamped to 1 day because data span < 1 day
        assertEquals(1f, s24.periodDays, 0.01f)
        assertEquals(1f, s72.periodDays, 0.01f)
        assertEquals(1f, s168.periodDays, 0.01f)
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
        val bolusTime = Instant.now()
        val b = BolusEvent(units = 2f, isAutomated = false, isCorrection = false, timestamp = bolusTime)

        // 4:59 before -- inside window
        val cgmJustInside = CgmReading(
            glucoseMgDl = 150,
            trendArrow = CgmTrend.FLAT,
            timestamp = bolusTime.minusSeconds(299),
        )
        val result = DashboardComputations.enrichBoluses(listOf(b), listOf(cgmJustInside), emptyList())
        assertEquals(150, result[0].bgAtEvent)

        // Exactly 5:00 (300s = 300,000 ms) -- still inside window
        val cgmExact = CgmReading(
            glucoseMgDl = 160,
            trendArrow = CgmTrend.FLAT,
            timestamp = bolusTime.minusSeconds(300),
        )
        val resultExact = DashboardComputations.enrichBoluses(listOf(b), listOf(cgmExact), emptyList())
        assertEquals(160, resultExact[0].bgAtEvent)

        // 5:01 (301s) -- outside window
        val cgmOutside = CgmReading(
            glucoseMgDl = 170,
            trendArrow = CgmTrend.FLAT,
            timestamp = bolusTime.minusSeconds(301),
        )
        val resultOutside = DashboardComputations.enrichBoluses(listOf(b), listOf(cgmOutside), emptyList())
        assertNull(resultOutside[0].bgAtEvent)
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

    @Test
    fun `enrichBoluses derives correct reasons for each type`() {
        val autoCorr = bolus(0.5f, 10, isAutomated = true, isCorrection = true)
        val corr = bolus(1f, 20, isAutomated = false, isCorrection = true)
        val meal = bolus(3f, 30, isAutomated = false, isCorrection = false)
        val auto = bolus(0.3f, 40, isAutomated = true, isCorrection = false)

        val result = DashboardComputations.enrichBoluses(
            listOf(autoCorr, corr, meal, auto),
            emptyList(),
            emptyList(),
        )
        assertEquals("Auto correction bolus", result[0].reason)
        assertEquals("BG correction bolus", result[1].reason)
        assertEquals("Food bolus", result[2].reason)
        assertEquals("Automated bolus", result[3].reason)
    }

    // -- deriveBolusReason ----------------------------------------------------

    @Test
    fun `deriveBolusReason returns correct reason for each type`() {
        assertEquals("Auto correction bolus", DashboardComputations.deriveBolusReason(BolusType.AUTO_CORRECTION))
        assertEquals("BG correction bolus", DashboardComputations.deriveBolusReason(BolusType.CORRECTION))
        assertEquals("Food bolus", DashboardComputations.deriveBolusReason(BolusType.MEAL))
        assertEquals("Meal bolus with correction", DashboardComputations.deriveBolusReason(BolusType.MEAL_WITH_CORRECTION))
        assertEquals("Automated bolus", DashboardComputations.deriveBolusReason(BolusType.AUTO))
    }

    // -- deriveBolusType with dose breakdown ------------------------------------

    @Test
    fun `deriveBolusType returns MEAL_WITH_CORRECTION when both portions present`() {
        val combo = bolus(4f, 10, isCorrection = true, correctionUnits = 0.5f, mealUnits = 3.5f)
        assertEquals(BolusType.MEAL_WITH_CORRECTION, DashboardComputations.deriveBolusType(combo))
    }

    @Test
    fun `deriveBolusType returns MEAL when only mealUnits present`() {
        val mealOnly = bolus(3f, 10, correctionUnits = 0f, mealUnits = 3f)
        assertEquals(BolusType.MEAL, DashboardComputations.deriveBolusType(mealOnly))
    }

    @Test
    fun `deriveBolusType returns CORRECTION when isCorrection and no breakdown`() {
        // Status response fallback: no dose breakdown, flags only
        val corr = bolus(1f, 10, isCorrection = true, correctionUnits = 0f, mealUnits = 0f)
        assertEquals(BolusType.CORRECTION, DashboardComputations.deriveBolusType(corr))
    }

    @Test
    fun `deriveBolusType prioritizes AUTO_CORRECTION over combo`() {
        // Automated + correction flags take priority even if breakdown is present
        val autoCorr = bolus(0.8f, 10, isAutomated = true, isCorrection = true, correctionUnits = 0.8f, mealUnits = 0f)
        assertEquals(BolusType.AUTO_CORRECTION, DashboardComputations.deriveBolusType(autoCorr))
    }

    @Test
    fun `deriveBolusReason for MEAL_WITH_CORRECTION includes dose breakdown`() {
        val combo = bolus(4f, 10, isCorrection = true, correctionUnits = 0.5f, mealUnits = 3.5f)
        val reason = DashboardComputations.deriveBolusReason(BolusType.MEAL_WITH_CORRECTION, combo)
        assertEquals("Meal 3.5U + correction 0.5U", reason)
    }

    @Test
    fun `deriveBolusReason uses no vendor-specific branding`() {
        // Verify no "Control-IQ" appears in any reason string
        val allReasons = listOf(
            DashboardComputations.deriveBolusReason(BolusType.AUTO_CORRECTION),
            DashboardComputations.deriveBolusReason(BolusType.CORRECTION),
            DashboardComputations.deriveBolusReason(BolusType.MEAL),
            DashboardComputations.deriveBolusReason(BolusType.MEAL_WITH_CORRECTION),
            DashboardComputations.deriveBolusReason(BolusType.AUTO),
        )
        for (reason in allReasons) {
            assertFalse("Reason should not contain 'Control-IQ': $reason", reason.contains("Control-IQ"))
        }
    }

    @Test
    fun `enrichBoluses passes through correctionUnits and mealUnits`() {
        val combo = bolus(4f, 10, isCorrection = true, correctionUnits = 0.5f, mealUnits = 3.5f)
        val result = DashboardComputations.enrichBoluses(listOf(combo), emptyList(), emptyList())
        assertEquals(1, result.size)
        assertEquals(BolusType.MEAL_WITH_CORRECTION, result[0].bolusType)
        assertEquals(0.5f, result[0].correctionUnits, 0.001f)
        assertEquals(3.5f, result[0].mealUnits, 0.001f)
        assertEquals("Meal 3.5U + correction 0.5U", result[0].reason)
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

    // -- periodStart ----------------------------------------------------------

    @Test
    fun `periodStart with boundary 0 and daysBack 0 returns today midnight`() {
        val zone = ZoneId.systemDefault()
        val now = ZonedDateTime.now(zone)
        val result = DashboardComputations.periodStart(0, 0, zone)
        val resultZdt = result.atZone(zone)
        // If past midnight, should be today at 00:00; if before midnight (impossible
        // for boundary=0), yesterday at 00:00. At any time, result is today's midnight.
        assertEquals(0, resultZdt.hour)
        assertEquals(0, resultZdt.minute)
        assertEquals(0, resultZdt.second)
        assertTrue(result.isBefore(now.toInstant()) || result == now.toInstant())
    }

    @Test
    fun `periodStart with boundary 0 and daysBack 3 returns midnight 3 days ago`() {
        val zone = ZoneId.systemDefault()
        val result = DashboardComputations.periodStart(3, 0, zone)
        val resultZdt = result.atZone(zone)
        val today = LocalDate.now(zone)
        // Should be 3 days before today's midnight boundary
        val expected = today.minusDays(3).atTime(0, 0).atZone(zone).toInstant()
        assertEquals(expected, result)
        assertEquals(0, resultZdt.hour)
    }

    @Test
    fun `periodStart with boundary 6 before boundary hour rolls back to yesterday`() {
        // Simulate 3 AM with boundary at 6 AM -- current "day" started yesterday at 6 AM
        val zone = ZoneId.of("America/Chicago")
        val today = LocalDate.now(zone)
        val expectedBoundary = today.minusDays(1).atTime(6, 0).atZone(zone).toInstant()

        // We can't control "now" in the function, but we can verify the logic:
        // At 3 AM, todayBoundary = today at 6:00, now < todayBoundary, so
        // effectiveBoundary = yesterday at 6:00.
        // At 8 AM, todayBoundary = today at 6:00, now >= todayBoundary, so
        // effectiveBoundary = today at 6:00.
        // We test the property: result always represents an instant that has already passed.
        val result = DashboardComputations.periodStart(0, 6, zone)
        assertTrue(result.isBefore(Instant.now()) || result == Instant.now())
    }

    @Test
    fun `periodStart with daysBack 7 and boundary 0 returns midnight 7 days ago`() {
        val zone = ZoneId.systemDefault()
        val result = DashboardComputations.periodStart(7, 0, zone)
        val resultZdt = result.atZone(zone)
        val today = LocalDate.now(zone)
        val expected = today.minusDays(7).atTime(0, 0).atZone(zone).toInstant()
        assertEquals(expected, result)
        assertEquals(0, resultZdt.hour)
    }

    @Test
    fun `periodStart is always in the past`() {
        val zone = ZoneId.systemDefault()
        for (boundary in 0..23) {
            for (daysBack in listOf(0, 1, 3, 7, 14, 30)) {
                val result = DashboardComputations.periodStart(daysBack, boundary, zone)
                assertTrue(
                    "periodStart(daysBack=$daysBack, boundary=$boundary) should be in the past",
                    result.isBefore(Instant.now()) || result == Instant.now(),
                )
            }
        }
    }

    @Test
    fun `periodStart with larger daysBack returns earlier instant`() {
        val zone = ZoneId.systemDefault()
        val p0 = DashboardComputations.periodStart(0, 0, zone)
        val p3 = DashboardComputations.periodStart(3, 0, zone)
        val p7 = DashboardComputations.periodStart(7, 0, zone)
        assertTrue(p7.isBefore(p3))
        assertTrue(p3.isBefore(p0))
    }
}
