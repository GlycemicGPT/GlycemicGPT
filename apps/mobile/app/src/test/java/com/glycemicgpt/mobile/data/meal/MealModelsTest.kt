package com.glycemicgpt.mobile.data.meal

import com.glycemicgpt.mobile.data.remote.dto.CommonFoodResponse
import com.glycemicgpt.mobile.data.remote.dto.EstimateDispersionResponse
import com.glycemicgpt.mobile.data.remote.dto.FoodRecordResponse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

class MealModelsTest {

    private fun record(
        source: String = "ai_estimate",
        confidence: String? = "high",
        correctedLow: Double? = null,
        correctedHigh: Double? = null,
        dispersion: EstimateDispersionResponse? = null,
    ) = FoodRecordResponse(
        id = "rec-1",
        mealTimestamp = "2026-06-14T12:00:00Z",
        foodDescription = "pasta bowl",
        carbsLow = 40.0,
        carbsHigh = 55.0,
        confidence = confidence,
        source = source,
        correctedCarbsLow = correctedLow,
        correctedCarbsHigh = correctedHigh,
        estimateDispersion = dispersion,
        createdAt = "2026-06-14T12:00:05Z",
    )

    @Test
    fun `maps an uncorrected AI estimate`() {
        val domain = record().toDomain()
        assertEquals(CarbRange(40.0, 55.0), domain.estimate)
        assertEquals(CarbConfidence.HIGH, domain.confidence)
        assertEquals(FoodRecordSource.AI_ESTIMATE, domain.source)
        assertFalse(domain.isCorrected)
        assertEquals(domain.estimate, domain.displayRange)
        assertEquals(Instant.parse("2026-06-14T12:00:00Z"), domain.mealTimestamp)
    }

    @Test
    fun `maps multi-sample dispersion when present (Story 50_H1)`() {
        val domain = record(
            dispersion = EstimateDispersionResponse(
                note = "Repeated looks at this photo disagreed a lot -- treat this as a rough guess.",
                wideSpread = true,
                identityAgreement = false,
            ),
        ).toDomain()
        val dispersion = domain.dispersion
        assertTrue("dispersion should be mapped", dispersion != null)
        assertEquals(true, dispersion?.wideSpread)
        assertEquals(false, dispersion?.identityAgreement)
        assertTrue(dispersion?.note?.contains("rough guess") == true)
    }

    @Test
    fun `dispersion is null on a history read that omits it`() {
        // History/list responses do not carry the transient create-time detail.
        assertNull(record(dispersion = null).toDomain().dispersion)
    }

    @Test
    fun `a blank dispersion note maps to null so the UI shows nothing`() {
        val domain = record(
            dispersion = EstimateDispersionResponse(note = "   ", wideSpread = false),
        ).toDomain()
        assertNull(domain.dispersion?.note)
    }

    @Test
    fun `correction is surfaced as the display range and preserves the original estimate`() {
        val domain = record(
            source = "user_corrected",
            correctedLow = 45.0,
            correctedHigh = 60.0,
        ).toDomain()
        assertTrue(domain.isCorrected)
        assertEquals(CarbRange(45.0, 60.0), domain.correction)
        assertEquals(CarbRange(45.0, 60.0), domain.displayRange)
        // Original AI estimate is never overwritten.
        assertEquals(CarbRange(40.0, 55.0), domain.estimate)
        assertEquals(FoodRecordSource.USER_CORRECTED, domain.source)
    }

    @Test
    fun `partial correction (only one bound) is treated as uncorrected`() {
        val domain = record(correctedLow = 45.0, correctedHigh = null).toDomain()
        assertFalse(domain.isCorrected)
        assertNull(domain.correction)
    }

    @Test
    fun `unknown confidence and source fall back to UNKNOWN`() {
        val domain = record(source = "something_new", confidence = "weird").toDomain()
        assertEquals(CarbConfidence.UNKNOWN, domain.confidence)
        assertEquals(FoodRecordSource.UNKNOWN, domain.source)
    }

    @Test
    fun `null confidence maps to UNKNOWN`() {
        assertEquals(CarbConfidence.UNKNOWN, CarbConfidence.fromApi(null))
    }

    @Test
    fun `malformed timestamps map to null rather than throwing`() {
        val domain = record().copy(mealTimestamp = "not-a-date").toDomain()
        assertNull(domain.mealTimestamp)
    }

    @Test
    fun `offset timestamps are parsed`() {
        assertEquals(
            Instant.parse("2026-06-14T12:00:00Z"),
            parseInstantOrNull("2026-06-14T12:00:00+00:00"),
        )
    }

    @Test
    fun `common food maps carbs range`() {
        val domain = CommonFoodResponse(
            id = "cf-1",
            name = "Pasta Bowl",
            carbsLow = 45.0,
            carbsHigh = 60.0,
            createdAt = "2026-06-14T12:00:00Z",
            updatedAt = "2026-06-14T12:30:00Z",
        ).toDomain()
        assertEquals("Pasta Bowl", domain.name)
        assertEquals(CarbRange(45.0, 60.0), domain.carbs)
    }

    @Test
    fun `carb bounds validation rejects out-of-range and inverted ranges`() {
        assertNull(CarbBounds.validate(40.0, 55.0))
        assertNull(CarbBounds.validate(50.0, 50.0))
        assertTrue(CarbBounds.validate(-1.0, 50.0)!!.contains("negative"))
        assertTrue(CarbBounds.validate(0.0, 1001.0)!!.contains("exceed"))
        assertTrue(CarbBounds.validate(60.0, 40.0)!!.contains("must not exceed"))
        assertTrue(CarbBounds.validate(Double.NaN, 40.0)!!.isNotEmpty())
    }
}
