package com.glycemicgpt.mobile.plugin.nightscout

import com.glycemicgpt.mobile.data.local.entity.CgmReadingEntity
import com.glycemicgpt.mobile.data.remote.dto.NightscoutDataDto
import com.glycemicgpt.mobile.data.remote.dto.NightscoutGlucoseReadingDto
import com.glycemicgpt.mobile.domain.freshness.Freshness
import com.glycemicgpt.mobile.domain.freshness.FreshnessPolicy
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.Instant

/**
 * AC5 verification (NO Nightscout integration change): a Nightscout-followed CGM value that stops
 * refreshing while the backend is down ages and de-emphasises through the SAME timestamp-based
 * staleness mechanism as a BLE reading.
 *
 * The invariant that makes this true is pinned here: the NS mapper stores the reading's REAL
 * capture timestamp (not the sync/fetch time) into the shared `cgm_readings` table, and the
 * freshness classifier is source-agnostic — it sees only that timestamp's age. No source-specific
 * or "aggressive" staleness logic exists or is needed.
 */
class NightscoutCgmFreshnessTest {

    private val now = Instant.parse("2026-03-01T12:00:00Z")

    private fun nsData(readingAt: Instant) = NightscoutDataDto(
        connectionId = "c1",
        // fetchedAt is "just now" — if the mapper ever stamped sync time instead of the reading's
        // capture time, the aged assertions below would fail.
        fetchedAt = now,
        effectiveLimitPerArray = 500,
        glucoseReadings = listOf(
            NightscoutGlucoseReadingDto(
                nsId = "g-1",
                readingTimestamp = readingAt,
                value = 120,
                trend = "Flat",
                trendRate = 0.0f,
                source = "nightscout:c1",
            ),
        ),
        pumpEvents = emptyList(),
    )

    private fun classify(entity: CgmReadingEntity): Freshness =
        FreshnessPolicy.CGM.classify(now.toEpochMilli() - entity.timestampMs)

    @Test
    fun `mapper stores the reading's real capture timestamp, not the sync time`() {
        val readingAt = now.minusSeconds(20 * 60)

        val entity = NightscoutDataMapper.toCgmEntities(nsData(readingAt)).single()

        assertEquals(readingAt.toEpochMilli(), entity.timestampMs)
    }

    @Test
    fun `frozen nightscout reading ages to TOO_STALE like any other source`() {
        // 20 minutes without a refresh: past the 15-minute TOO_STALE bound.
        val entity = NightscoutDataMapper.toCgmEntities(nsData(now.minusSeconds(20 * 60))).single()

        assertEquals(Freshness.TOO_STALE, classify(entity))
    }

    @Test
    fun `nightscout and BLE readings of the same age classify identically`() {
        val readingAt = now.minusSeconds(8 * 60) // past STALE, below TOO_STALE

        val nsEntity = NightscoutDataMapper.toCgmEntities(nsData(readingAt)).single()
        val bleEntity = CgmReadingEntity(
            glucoseMgDl = 120,
            trendArrow = "FLAT",
            source = "",
            timestampMs = readingAt.toEpochMilli(),
        )

        assertEquals(Freshness.STALE, classify(nsEntity))
        assertEquals(classify(bleEntity), classify(nsEntity))
    }

    @Test
    fun `fresh nightscout reading classifies FRESH`() {
        val entity = NightscoutDataMapper.toCgmEntities(nsData(now.minusSeconds(60))).single()

        assertEquals(Freshness.FRESH, classify(entity))
    }
}
