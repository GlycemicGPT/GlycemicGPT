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
import kotlin.math.abs
import kotlin.math.sqrt

object DashboardComputations {

    /** Minimum readings required for AGP (roughly 3 days of 5-min intervals). */
    private const val MIN_AGP_READINGS = 864

    /** Maximum time delta (ms) for cross-referencing CGM/IoB to a bolus event. */
    private const val CROSS_REF_WINDOW_MS = 5L * 60_000L

    fun computeAgp(readings: List<CgmReading>, periodDays: Int): AgpProfile? {
        if (readings.size < MIN_AGP_READINGS) return null

        val zone = ZoneId.systemDefault()
        val byHour = readings.groupBy { it.timestamp.atZone(zone).hour }

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
            totalReadings = readings.size,
            periodDays = periodDays,
        )
    }

    fun computeCgmStats(readings: List<CgmReading>): CgmStats? {
        if (readings.isEmpty()) return null

        val values = readings.map { it.glucoseMgDl.toFloat() }
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
            readingsCount = readings.size,
        )
    }

    fun computeInsulinSummary(
        basals: List<BasalReading>,
        boluses: List<BolusEvent>,
        periodHours: Long,
    ): InsulinSummary? {
        val bolusUnits = boluses.sumOf { it.units.toDouble() }.toFloat()
        val basalUnits = computeBasalIntegral(basals)
        val total = basalUnits + bolusUnits
        if (total <= 0f) return null

        // Use actual data span instead of selected period to avoid dividing
        // 2 days of data by 7 days when user selects "7D" with limited history
        val allTimestamps = basals.map { it.timestamp.toEpochMilli() } +
            boluses.map { it.timestamp.toEpochMilli() }
        val dataSpanHours = if (allTimestamps.size >= 2) {
            val spanMs = allTimestamps.max() - allTimestamps.min()
            (spanMs / 3_600_000.0).toFloat()
        } else {
            periodHours.toFloat()
        }
        val days = (dataSpanHours / 24f).coerceIn(1f, periodHours / 24f)
        val tdd = total / days

        return InsulinSummary(
            totalDailyDose = tdd,
            basalUnits = basalUnits / days,
            bolusUnits = bolusUnits / days,
            basalPercent = (basalUnits / total) * 100f,
            bolusPercent = (bolusUnits / total) * 100f,
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

            EnrichedBolusEvent(
                units = bolus.units,
                bolusType = deriveBolusType(bolus),
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

    private fun deriveBolusType(bolus: BolusEvent): BolusType = when {
        bolus.isAutomated && bolus.isCorrection -> BolusType.AUTO_CORRECTION
        bolus.isCorrection -> BolusType.CORRECTION
        bolus.isAutomated -> BolusType.AUTO
        else -> BolusType.MEAL
    }
}
