package com.glycemicgpt.mobile.plugin.nightscout

import com.glycemicgpt.mobile.data.remote.dto.NightscoutDataDto
import com.glycemicgpt.mobile.data.remote.dto.NightscoutGlucoseReadingDto
import com.glycemicgpt.mobile.data.remote.dto.NightscoutPumpEventDto
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class NightscoutDataMapperTest {

    private fun data(
        glucose: List<NightscoutGlucoseReadingDto> = emptyList(),
        events: List<NightscoutPumpEventDto> = emptyList(),
    ) = NightscoutDataDto(
        connectionId = "c1",
        fetchedAt = Instant.parse("2026-03-01T12:00:00Z"),
        effectiveLimitPerArray = 500,
        glucoseReadings = glucose,
        pumpEvents = events,
    )

    private fun glucose(value: Int, ts: String, trend: String = "Flat") =
        NightscoutGlucoseReadingDto(
            nsId = "g-$ts",
            readingTimestamp = Instant.parse(ts),
            value = value,
            trend = trend,
            trendRate = 0.0f,
            source = "nightscout:c1",
        )

    private fun event(type: String, ts: String, units: Float?, automated: Boolean = false) =
        NightscoutPumpEventDto(
            nsId = "e-$type-$ts",
            eventTimestamp = Instant.parse(ts),
            eventType = type,
            units = units,
            durationMinutes = null,
            isAutomated = automated,
            source = "nightscout:c1",
        )

    @Test
    fun `glucose maps to cgm entities with value and epoch ms`() {
        val out = NightscoutDataMapper.toCgmEntities(
            data(glucose = listOf(glucose(142, "2026-03-01T12:00:00Z", "SingleUp")))
        )
        assertEquals(1, out.size)
        assertEquals(142, out[0].glucoseMgDl)
        assertEquals("SingleUp", out[0].trendArrow)
        assertEquals(NightscoutDataMapper.SOURCE, out[0].source)
        assertEquals(Instant.parse("2026-03-01T12:00:00Z").toEpochMilli(), out[0].timestampMs)
    }

    @Test
    fun `boluses carry the nightscout-source attribution and correction flag`() {
        val out = NightscoutDataMapper.toBolusEntities(
            data(
                events = listOf(
                    event("bolus", "2026-03-01T12:00:00Z", 2.5f),
                    event("correction", "2026-03-01T12:05:00Z", 0.8f, automated = true),
                )
            )
        )
        assertEquals(2, out.size)
        assertTrue(out.all { it.source == NightscoutDataMapper.SOURCE })
        assertEquals(false, out[0].isCorrection)
        assertEquals(true, out[1].isCorrection)
        assertEquals(true, out[1].isAutomated)
    }

    @Test
    fun `non-delivery and unit-less events are excluded from bolus and basal`() {
        val out = NightscoutDataMapper.toBolusEntities(
            data(
                events = listOf(
                    event("note", "2026-03-01T12:00:00Z", null),
                    event("bg_reading", "2026-03-01T12:01:00Z", null),
                    event("bolus", "2026-03-01T12:02:00Z", null), // bolus but no units
                )
            )
        )
        assertTrue(out.isEmpty())
    }

    @Test
    fun `basal events map to basal readings with rate`() {
        val out = NightscoutDataMapper.toBasalEntities(
            data(events = listOf(event("basal", "2026-03-01T12:00:00Z", 0.65f, automated = true)))
        )
        assertEquals(1, out.size)
        assertEquals(0.65f, out[0].rate)
        assertEquals(true, out[0].isAutomated)
        assertEquals(NightscoutDataMapper.SOURCE, out[0].source)
    }
}
