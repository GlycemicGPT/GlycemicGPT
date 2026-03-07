package com.glycemicgpt.mobile.domain.compute

import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BolusCategory
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.BolusType
import com.glycemicgpt.mobile.domain.model.CategoryStats
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmStats
import com.glycemicgpt.mobile.domain.model.EnrichedBolusEvent
import com.glycemicgpt.mobile.domain.model.InsulinSummary
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.plugin.capabilities.BolusCategoryProvider
import java.time.Instant
import java.time.ZoneId
import java.time.ZonedDateTime
import java.util.Locale
import kotlin.math.abs
import kotlin.math.sqrt

object DashboardComputations {

    /** Maximum time delta (ms) for cross-referencing CGM/IoB to a bolus event. */
    private const val CROSS_REF_WINDOW_MS = 5L * 60_000L

    /** Valid CGM glucose range (mg/dL) -- filters sensor noise and impossible values. */
    private const val VALID_GLUCOSE_MIN = 20
    private const val VALID_GLUCOSE_MAX = 500

    /**
     * Compute the start instant for an analytics period aligned to the day boundary.
     *
     * For [daysBack]=0 (24H): returns today's boundary hour (or yesterday's if we
     * haven't passed it yet). For [daysBack]=3 (3D): returns the boundary 3 days
     * before the effective boundary. This matches the pump's Delivery Summary which
     * resets at midnight (boundary=0).
     *
     * @param daysBack Number of additional days to go back (0 for current day period).
     * @param boundaryHour Hour (0-23) when the analytics day resets.
     * @param zone Time zone for local-time boundary calculation.
     * @return The [Instant] at which the analytics period starts.
     */
    fun periodStart(
        daysBack: Int,
        boundaryHour: Int,
        zone: ZoneId = ZoneId.systemDefault(),
        now: ZonedDateTime = ZonedDateTime.now(zone),
    ): Instant {
        require(boundaryHour in 0..23) { "boundaryHour must be 0-23, got $boundaryHour" }
        val todayBoundary = now.toLocalDate().atTime(boundaryHour, 0).atZone(zone)
        val effectiveBoundary = if (now.isBefore(todayBoundary)) {
            todayBoundary.minusDays(1)
        } else {
            todayBoundary
        }
        return effectiveBoundary.minusDays(daysBack.toLong()).toInstant()
    }

    fun computeCgmStats(readings: List<CgmReading>): CgmStats? {
        val valid = readings.filter { it.glucoseMgDl in VALID_GLUCOSE_MIN..VALID_GLUCOSE_MAX }
        if (valid.isEmpty()) return null

        val values = valid.map { it.glucoseMgDl.toFloat() }
        val mean = values.sum() / values.size
        val denominator = if (values.size > 1) values.size - 1 else 1
        val variance = values.sumOf { ((it - mean) * (it - mean)).toDouble() } / denominator
        val stdDev = sqrt(variance).toFloat()
        val cvPercent = if (mean > 0f) (stdDev / mean) * 100f else 0f
        val gmi = 3.31f + 0.02392f * mean

        return CgmStats(
            meanGlucose = mean,
            stdDev = stdDev,
            cvPercent = cvPercent,
            gmi = gmi,
            readingsCount = valid.size,
        )
    }

    fun computeInsulinSummary(
        basals: List<BasalReading>,
        boluses: List<BolusEvent>,
        periodHours: Long,
        categoryProvider: BolusCategoryProvider? = null,
    ): InsulinSummary? {
        if (periodHours <= 0L) return null

        val totalBolus = boluses.sumOf { it.units.toDouble() }.toFloat()
        val totalBasal = computeBasalIntegral(basals)
        val total = totalBasal + totalBolus
        if (total <= 0f) return null

        // Divide by actual data span (oldest event to now), capped at the selected period.
        // Uses nowMs (not newestMs) intentionally -- computeBasalIntegral also extends
        // the last basal segment to now, so the denominator must match the numerator.
        // Minimum 1 day to avoid inflating sub-day data into huge daily projections.
        val nowMs = System.currentTimeMillis()
        val allTimestamps = basals.map { it.timestamp.toEpochMilli() } +
            boluses.map { it.timestamp.toEpochMilli() }
        val oldestMs = allTimestamps.minOrNull() ?: nowMs
        val dataSpanHours = ((nowMs - oldestMs) / 3_600_000.0).toFloat()
        val days = (dataSpanHours / 24f).coerceIn(1f, periodHours / 24f)

        val correctionBoluses = boluses.filter { it.isCorrection || it.correctionUnits > 0f }
        val totalCorrection = correctionBoluses.sumOf {
            if (it.correctionUnits > 0f) it.correctionUnits.toDouble() else it.units.toDouble()
        }.toFloat()

        // Portion-based accumulation: split each bolus into food and correction
        // portions instead of putting the full amount into one category.
        var foodPortionTotal = 0.0
        var correctionPortionTotal = 0.0

        // Category breakdown: count + portions per category
        val categoryMap = mutableMapOf<BolusCategory, MutableCategoryAccum>()

        for (b in boluses) {
            val category = BolusCategoryMapper.resolve(b, categoryProvider)
            val accum = categoryMap.getOrPut(category) { MutableCategoryAccum() }
            accum.count++
            accum.totalUnits += b.units.toDouble()

            if (b.isAutomated) {
                // Automated boluses are always correction (no meal component)
                val corrPortion = if (b.correctionUnits > 0f) {
                    b.correctionUnits.toDouble()
                } else {
                    b.units.toDouble()
                }
                correctionPortionTotal += corrPortion
                accum.correctionPortion += corrPortion
            } else if (b.mealUnits > 0f || b.correctionUnits > 0f) {
                // Has dose breakdown -- use the portions directly
                foodPortionTotal += b.mealUnits.toDouble()
                correctionPortionTotal += b.correctionUnits.toDouble()
                accum.foodPortion += b.mealUnits.toDouble()
                accum.correctionPortion += b.correctionUnits.toDouble()
            } else if (b.isCorrection) {
                // No breakdown, correction flag only -- full amount is correction
                correctionPortionTotal += b.units.toDouble()
                accum.correctionPortion += b.units.toDouble()
            } else {
                // No breakdown, no correction flag -- assume food
                foodPortionTotal += b.units.toDouble()
                accum.foodPortion += b.units.toDouble()
            }
        }

        val categoryBreakdown = categoryMap.mapValues { (_, accum) ->
            CategoryStats(
                count = accum.count,
                totalUnits = accum.totalUnits.toFloat(),
                foodPortion = accum.foodPortion.toFloat(),
                correctionPortion = accum.correctionPortion.toFloat(),
            )
        }

        val tdd = total / days
        val basalPerDay = totalBasal / days
        val bolusPerDay = totalBolus / days
        val corrPerDay = totalCorrection / days

        val basalPct = if (tdd > 0f) (basalPerDay / tdd) * 100f else 0f
        return InsulinSummary(
            totalDailyDose = tdd,
            basalUnits = basalPerDay,
            bolusUnits = bolusPerDay,
            correctionUnits = corrPerDay,
            basalPercent = basalPct,
            bolusPercent = if (tdd > 0f) 100f - basalPct else 0f,
            bolusCount = boluses.size,
            correctionCount = correctionBoluses.size,
            foodBolusUnits = (foodPortionTotal / days).toFloat(),
            correctionBolusUnits = (correctionPortionTotal / days).toFloat(),
            categoryBreakdown = categoryBreakdown,
            periodDays = days,
        )
    }

    private class MutableCategoryAccum {
        var count: Int = 0
        var totalUnits: Double = 0.0
        var foodPortion: Double = 0.0
        var correctionPortion: Double = 0.0
    }

    /**
     * Cross-reference boluses with nearest CGM/IoB readings within a +/-5min window.
     *
     * @param cgmReadings must be sorted ascending by timestamp (as returned by DAO queries).
     * @param iobReadings must be sorted ascending by timestamp (as returned by DAO queries).
     */
    fun enrichBoluses(
        boluses: List<BolusEvent>,
        cgmReadings: List<CgmReading>,
        iobReadings: List<IoBReading>,
    ): List<EnrichedBolusEvent> {
        if (boluses.isEmpty()) return emptyList()

        // Defensive sort -- DAO queries return ASC order, but callers may not guarantee it
        val sortedCgm = if (cgmReadings.size <= 1 || isSortedAsc(cgmReadings) { it.timestamp.toEpochMilli() }) {
            cgmReadings
        } else {
            cgmReadings.sortedBy { it.timestamp }
        }
        val sortedIoB = if (iobReadings.size <= 1 || isSortedAsc(iobReadings) { it.timestamp.toEpochMilli() }) {
            iobReadings
        } else {
            iobReadings.sortedBy { it.timestamp }
        }

        return boluses.map { bolus ->
            val bolusMs = bolus.timestamp.toEpochMilli()
            val nearestCgm = findNearestCgm(sortedCgm, bolusMs)
            val nearestIoB = findNearestIoB(sortedIoB, bolusMs)

            val type = deriveBolusType(bolus)
            EnrichedBolusEvent(
                units = bolus.units,
                bolusType = type,
                reason = deriveBolusReason(type, bolus),
                correctionUnits = bolus.correctionUnits,
                mealUnits = bolus.mealUnits,
                bgAtEvent = nearestCgm,
                iobAtEvent = nearestIoB,
                timestamp = bolus.timestamp,
            )
        }
    }

    internal fun computeBasalIntegral(basals: List<BasalReading>): Float {
        if (basals.isEmpty()) return 0f

        val nowMs = System.currentTimeMillis()
        var totalUnits = 0.0
        for (i in basals.indices) {
            val nextMs = if (i + 1 < basals.size) {
                basals[i + 1].timestamp.toEpochMilli()
            } else {
                nowMs
            }
            val durationHours = (nextMs - basals[i].timestamp.toEpochMilli()) / 3_600_000.0
            // Cap segment duration at 2 hours to avoid inflated gaps
            val capped = durationHours.coerceAtMost(2.0).coerceAtLeast(0.0)
            totalUnits += basals[i].rate * capped
        }
        return totalUnits.toFloat()
    }

    private fun findNearestCgm(readings: List<CgmReading>, targetMs: Long): Int? {
        if (readings.isEmpty()) return null
        val nearest = findNearest(readings, targetMs) { it.timestamp.toEpochMilli() }
        val delta = abs(nearest.timestamp.toEpochMilli() - targetMs)
        return if (delta <= CROSS_REF_WINDOW_MS) nearest.glucoseMgDl else null
    }

    private fun findNearestIoB(readings: List<IoBReading>, targetMs: Long): Float? {
        if (readings.isEmpty()) return null
        val nearest = findNearest(readings, targetMs) { it.timestamp.toEpochMilli() }
        val delta = abs(nearest.timestamp.toEpochMilli() - targetMs)
        return if (delta <= CROSS_REF_WINDOW_MS) nearest.iob else null
    }

    private fun <T> findNearest(items: List<T>, targetMs: Long, getMs: (T) -> Long): T {
        var lo = 0
        var hi = items.lastIndex
        while (lo < hi) {
            val mid = (lo + hi) / 2
            if (getMs(items[mid]) < targetMs) lo = mid + 1 else hi = mid
        }
        val candidates = listOfNotNull(items.getOrNull(lo), items.getOrNull(lo - 1))
        return candidates.minBy { abs(getMs(it) - targetMs) }
    }

    private fun <T> isSortedAsc(items: List<T>, getMs: (T) -> Long): Boolean {
        for (i in 0 until items.lastIndex) {
            if (getMs(items[i]) > getMs(items[i + 1])) return false
        }
        return true
    }

    internal fun deriveBolusType(bolus: BolusEvent): BolusType = when {
        bolus.isAutomated && bolus.isCorrection -> BolusType.AUTO_CORRECTION
        bolus.mealUnits > 0f && bolus.correctionUnits > 0f -> BolusType.MEAL_WITH_CORRECTION
        bolus.isCorrection && !bolus.isAutomated -> BolusType.CORRECTION
        bolus.isAutomated -> BolusType.AUTO
        else -> BolusType.MEAL
    }

    internal fun deriveBolusReason(type: BolusType, bolus: BolusEvent? = null): String = when (type) {
        BolusType.AUTO_CORRECTION -> "Auto correction bolus"
        BolusType.CORRECTION -> "BG correction bolus"
        BolusType.MEAL -> "Food bolus"
        BolusType.MEAL_WITH_CORRECTION -> {
            val meal = bolus?.mealUnits ?: 0f
            val corr = bolus?.correctionUnits ?: 0f
            if (meal > 0f && corr > 0f) {
                String.format(Locale.US, "Meal %.1fU + correction %.1fU", meal, corr)
            } else {
                "Meal bolus with correction"
            }
        }
        BolusType.AUTO -> "Automated bolus"
    }
}
