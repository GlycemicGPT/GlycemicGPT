package com.glycemicgpt.mobile.data.meal

import com.glycemicgpt.mobile.data.remote.dto.AuditDispersionResponse
import com.glycemicgpt.mobile.data.remote.dto.AuditPrecedenceResponse
import com.glycemicgpt.mobile.data.remote.dto.AuditSampleResponse
import com.glycemicgpt.mobile.data.remote.dto.CommonFoodResponse
import com.glycemicgpt.mobile.data.remote.dto.EstimateDispersionResponse
import com.glycemicgpt.mobile.data.remote.dto.FoodRecordAuditResponse
import com.glycemicgpt.mobile.data.remote.dto.FoodRecordResponse
import com.glycemicgpt.mobile.data.remote.dto.MacroFactResponse
import com.glycemicgpt.mobile.data.remote.dto.NetCarbsResponse
import com.glycemicgpt.mobile.data.remote.dto.NutritionFactsResponse
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
        confirmedFoodName: String? = null,
        identityConfirmed: Boolean = false,
        suggestedIdentity: String? = null,
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
        confirmedFoodName = confirmedFoodName,
        identityConfirmed = identityConfirmed,
        suggestedIdentity = suggestedIdentity,
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

    // --- Food-identity confirmation mapping (Story 50.H2) ---

    @Test
    fun `unconfirmed estimate maps identity from the AI description`() {
        val domain = record().toDomain()
        assertFalse(domain.identityConfirmed)
        assertNull(domain.confirmedFoodName)
        assertEquals("pasta bowl", domain.displayIdentity) // the AI's guess
    }

    @Test
    fun `confirmed identity is surfaced and preferred over the AI description`() {
        val domain = record(
            confirmedFoodName = "homemade lasagna",
            identityConfirmed = true,
        ).toDomain()
        assertTrue(domain.identityConfirmed)
        assertEquals("homemade lasagna", domain.confirmedFoodName)
        assertEquals("homemade lasagna", domain.displayIdentity) // confirmed wins
    }

    @Test
    fun `own-history suggestion is mapped (blank to null)`() {
        assertEquals("my chili", record(suggestedIdentity = "my chili").toDomain().suggestedIdentity)
        assertNull(record(suggestedIdentity = "  ").toDomain().suggestedIdentity)
    }

    // --- Audit provenance mapping (Story 50.H3) ---

    @Test
    fun `grounded audit maps samples, precedence, and dispersion`() {
        val domain = FoodRecordAuditResponse(
            foodRecordId = "rec-1",
            samples = listOf(
                AuditSampleResponse(carbsLow = 40.0, carbsHigh = 50.0, identity = "pasta"),
                AuditSampleResponse(carbsLow = 60.0, carbsHigh = 70.0, identity = "pasta"),
            ),
            dispersion = AuditDispersionResponse(
                confidence = "medium",
                samplesUsed = 2,
                wideSpread = true,
                identityAgreement = true,
            ),
            precedence = AuditPrecedenceResponse(
                outcome = "grounded",
                chosenSource = "Your meal history",
                identityUsed = "pasta",
                identityConfirmed = true,
            ),
            createdAt = "2026-06-14T12:00:05Z",
        ).toDomain()

        assertEquals(2, domain.samples.size)
        assertEquals(CarbRange(40.0, 50.0), domain.samples[0].carbs)
        assertEquals("pasta", domain.samples[0].identity)
        assertEquals(CarbConfidence.MEDIUM, domain.confidence)
        assertEquals(2, domain.samplesUsed)
        assertTrue(domain.grounded)
        assertEquals("Your meal history", domain.groundingSource)
        assertEquals("pasta", domain.identityUsed)
    }

    // --- Glucose-framed nutrition mapping (Story 50.N1) ---

    @Test
    fun `nutrition facts map portion, framed macros, and caveated net carbs`() {
        val domain = record().copy(
            nutritionFacts = NutritionFactsResponse(
                portion = "one large bowl",
                macros = listOf(
                    MacroFactResponse(
                        key = "protein_grams",
                        label = "Protein",
                        value = 12.0,
                        unit = "g",
                        glucoseNote = "Protein can nudge glucose up later, in the hours after a meal.",
                    ),
                ),
                netCarbs = NetCarbsResponse(
                    low = 34.0,
                    high = 49.0,
                    caveat = "Net carbs ... the ADA recommends counting total carbs ... never use it to dose or bolus.",
                ),
                disclaimer = "These nutrition figures ... never use it to dose or bolus.",
            ),
        ).toDomain()

        val facts = domain.nutritionFacts
        assertTrue("nutrition facts should be mapped", facts != null)
        assertEquals("one large bowl", facts?.portion)
        assertEquals("Protein", facts?.macros?.first()?.label)
        assertEquals("g", facts?.macros?.first()?.unit)
        assertTrue(facts?.macros?.first()?.glucoseNote?.contains("later") == true)
        assertEquals(34.0, facts?.netCarbs?.low)
        assertEquals(49.0, facts?.netCarbs?.high)
        assertTrue(facts?.netCarbs?.caveat?.contains("dose or bolus") == true)
    }

    @Test
    fun `nutrition facts are null on a read that omits them`() {
        assertNull(record().toDomain().nutritionFacts)
    }

    @Test
    fun `a blank portion maps to null so the UI shows nothing`() {
        val domain = record().copy(
            nutritionFacts = NutritionFactsResponse(portion = "  "),
        ).toDomain()
        assertNull(domain.nutritionFacts?.portion)
    }

    @Test
    fun `non-finite macro values are dropped and an inverted net-carb band is skipped`() {
        // Defensive client mirror of the server bounds: a NaN/Infinity figure must
        // never render on a medical surface, and an inverted band is not shown.
        val domain = record().copy(
            nutritionFacts = NutritionFactsResponse(
                macros = listOf(
                    MacroFactResponse("protein_grams", "Protein", Double.NaN, "g", null),
                    MacroFactResponse("fat_grams", "Fat", Double.POSITIVE_INFINITY, "g", null),
                    MacroFactResponse("calories", "Calories", 640.0, "kcal", null),
                ),
                netCarbs = NetCarbsResponse(low = 40.0, high = 10.0, caveat = "x"),
            ),
        ).toDomain()

        val facts = domain.nutritionFacts!!
        assertEquals(listOf("Calories"), facts.macros.map { it.label })
        assertNull(facts.netCarbs)
    }

    @Test
    fun `vision-only audit is not grounded`() {
        val domain = FoodRecordAuditResponse(
            foodRecordId = "rec-1",
            samples = emptyList(),
            precedence = AuditPrecedenceResponse(outcome = "vision_only", identityConfirmed = false),
        ).toDomain()
        assertFalse(domain.grounded)
        assertNull(domain.groundingSource)
    }
}
