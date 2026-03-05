package com.glycemicgpt.mobile.domain.compute

import com.glycemicgpt.mobile.domain.model.AgpBucket
import com.glycemicgpt.mobile.domain.model.AgpProfile
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.BolusType
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmStats
import com.glycemicgpt.mobile.domain.model.EnrichedBolusEvent
import com.glycemicgpt.mobile.domain.model.InsulinSummary
import com.glycemicgpt.mobile.domain.model.IoBReading
import java.time.ZoneId
import java.util.Locale
import kotlin.math.abs
import kotlin.math.sqrt

object DashboardComputations {

    /** Minimum readings required for AGP (roughly 3 days of 5-min intervals). */
    private const val MIN_AGP_READINGS = 864

    /** Maximum time delta (ms) for cross-referencing CGM/IoB to a bolus event. */
    private const val CROSS_REF_WINDOW_MS = 5L * 60_000L

    /** Valid CGM glucose range (mg/dL) -- filters sensor noise and impossible values. */
    private const val VALID_GLUCOSE_MIN = 20
    private const val VALID_GLUCOSE_MAX = 500

    fun computeAgp(readings: List<CgmReading>, periodDays: Int): AgpProfile? {
        val valid = readings.filter { it.glucoseMgDl in VALID_GLUCOSE_MIN..VALID_GLUCOSE_MAX }
        if (valid.size < MIN_AGP_READINGS) return null

        val zone = ZoneId.systemDefault()
        val byHour = valid.groupBy { it.timestamp.atZone(zone).hour }

        val buckets = (0..23).map { hour ->
            val hourReadings = byHour[hour]
            if (hourReadings.isNullOrEmpty()) {
                AgpBucket(hour, 0f, 0f, 0f, 0f, 0f, 0)
            } else {
                val sorted = hourReadings.map { it.glucoseMgDl.toFloat() }.sorted()
                AgpBucket(
                    hour = hour,
                    p10 = percentile(sorted, 10f),
                    p25 = percentile(sorted, 25f),
                    p50 = percentile(sorted, 50f),
                    p75 = percentile(sorted, 75f),
                    p90 = percentile(sorted, 90f),
                    count = sorted.size,
                )
            }
        }

        return AgpProfile(
            buckets = buckets,
            totalReadings = valid.size,
            periodDays = periodDays,
        )
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
    ): InsulinSummary? {
        if (periodHours <= 0L) return null

        val totalBolus = boluses.sumOf { it.units.toDouble() }.toFloat()
        val totalBasal = computeBasalIntegral(basals)
        val total = totalBasal + totalBolus
        if (total <= 0f) return null

        // Divide by actual data span (oldest event to now), capped at the selected period.
        // Uses nowMs (not newestMs) intentionally -- computeBasalIntegral also extends
        // the last basal segment to now, so the denominator must match the numerator.
        // Mobile only has ~7 days of local BLE data, so selecting "7D" with 1 day
        // of data should still show the 1-day average, not dilute it by 7.
        // Minimum 1 day to avoid inflating sub-day data into huge daily projections.
        val nowMs = System.currentTimeMillis()
        val allTimestamps = basals.map { it.timestamp.toEpochMilli() } +
            boluses.map { it.timestamp.toEpochMilli() }
        val oldestMs = allTimestamps.minOrNull() ?: nowMs
        val dataSpanHours = ((nowMs - oldestMs) / 3_600_000.0).toFloat()
        val days = (dataSpanHours / 24f).coerceIn(1f, periodHours / 24f)

        val correctionBoluses = boluses.filter { it.isCorrection || it.correctionUnits > 0f }
        // Use breakdown when available; fall back to full units for flag-only
        // boluses (status response with no dose breakdown). This may overcount
        // correction insulin if isCorrection is set on a combo bolus with no
        // breakdown data, but that case does not occur with Tandem pump data.
        val totalCorrection = correctionBoluses.sumOf {
            if (it.correctionUnits > 0f) it.correctionUnits.toDouble() else it.units.toDouble()
        }.toFloat()

        // Per-category breakdown (mirrors pump Delivery Summary)
        var foodTotal = 0.0
        var corrTotal = 0.0     // AUTO_CORRECTION + AUTO
        var bgFoodTotal = 0.0   // MEAL_WITH_CORRECTION
        var bgOnlyTotal = 0.0   // CORRECTION

        for (b in boluses) {
            when (deriveBolusType(b)) {
                BolusType.MEAL -> foodTotal += b.units.toDouble()
                BolusType.AUTO_CORRECTION, BolusType.AUTO -> corrTotal += b.units.toDouble()
                BolusType.MEAL_WITH_CORRECTION -> bgFoodTotal += b.units.toDouble()
                BolusType.CORRECTION -> bgOnlyTotal += b.units.toDouble()
            }
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
            foodBolusUnits = (foodTotal / days).toFloat(),
            correctionBolusUnits = (corrTotal / days).toFloat(),
            bgFoodUnits = (bgFoodTotal / days).toFloat(),
            bgOnlyUnits = (bgOnlyTotal / days).toFloat(),
            periodDays = days,
        )
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

    internal fun percentile(sorted: List<Float>, p: Float): Float {
        if (sorted.isEmpty()) return 0f
        if (sorted.size == 1) return sorted[0]

        val rank = (p / 100f) * (sorted.size - 1)
        val lower = rank.toInt()
        val upper = (lower + 1).coerceAtMost(sorted.lastIndex)
        val fraction = rank - lower

        return sorted[lower] + fraction * (sorted[upper] - sorted[lower])
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
