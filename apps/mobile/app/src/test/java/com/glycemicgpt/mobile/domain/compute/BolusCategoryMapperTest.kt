package com.glycemicgpt.mobile.domain.compute

import com.glycemicgpt.mobile.domain.model.BolusCategory
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.plugin.capabilities.BolusCategoryProvider
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.Instant

class BolusCategoryMapperTest {

    private val now = Instant.now()

    private fun bolus(
        units: Float = 1f,
        isAutomated: Boolean = false,
        isCorrection: Boolean = false,
        correctionUnits: Float = 0f,
        mealUnits: Float = 0f,
        category: String = "",
    ) = BolusEvent(
        units = units,
        isAutomated = isAutomated,
        isCorrection = isCorrection,
        correctionUnits = correctionUnits,
        mealUnits = mealUnits,
        category = category,
        timestamp = now,
    )

    private val testProvider = object : BolusCategoryProvider {
        override fun declaredCategories() = setOf("CONTROL_IQ", "FOOD_ONLY", "BG_FOOD")
        override fun toPlatformCategory(pluginCategory: String) = when (pluginCategory) {
            "CONTROL_IQ" -> "AUTO_CORRECTION"
            "FOOD_ONLY" -> "FOOD"
            "BG_FOOD" -> "FOOD_AND_CORRECTION"
            else -> null
        }
    }

    @Test
    fun `resolve uses provider when category is set`() {
        val b = bolus(category = "CONTROL_IQ", isAutomated = true)
        assertEquals(BolusCategory.AUTO_CORRECTION, BolusCategoryMapper.resolve(b, testProvider))
    }

    @Test
    fun `resolve falls back to flags when category is empty`() {
        val b = bolus(isAutomated = true, isCorrection = true)
        assertEquals(BolusCategory.AUTO_CORRECTION, BolusCategoryMapper.resolve(b, testProvider))
    }

    @Test
    fun `resolve falls back to flags when provider is null`() {
        val b = bolus(category = "CONTROL_IQ", isAutomated = true)
        assertEquals(BolusCategory.AUTO_CORRECTION, BolusCategoryMapper.resolve(b, null))
    }

    @Test
    fun `resolve falls back to flags when provider returns null`() {
        val b = bolus(category = "UNKNOWN_CATEGORY", isCorrection = true)
        assertEquals(BolusCategory.CORRECTION, BolusCategoryMapper.resolve(b, testProvider))
    }

    @Test
    fun `deriveFromFlags automated returns AUTO_CORRECTION`() {
        assertEquals(BolusCategory.AUTO_CORRECTION, BolusCategoryMapper.deriveFromFlags(bolus(isAutomated = true)))
    }

    @Test
    fun `deriveFromFlags combo returns FOOD_AND_CORRECTION`() {
        val b = bolus(mealUnits = 3f, correctionUnits = 1f)
        assertEquals(BolusCategory.FOOD_AND_CORRECTION, BolusCategoryMapper.deriveFromFlags(b))
    }

    @Test
    fun `deriveFromFlags correction flag returns CORRECTION`() {
        assertEquals(BolusCategory.CORRECTION, BolusCategoryMapper.deriveFromFlags(bolus(isCorrection = true)))
    }

    @Test
    fun `deriveFromFlags meal only returns FOOD`() {
        assertEquals(BolusCategory.FOOD, BolusCategoryMapper.deriveFromFlags(bolus(mealUnits = 3f)))
    }

    @Test
    fun `deriveFromFlags plain bolus returns FOOD`() {
        assertEquals(BolusCategory.FOOD, BolusCategoryMapper.deriveFromFlags(bolus()))
    }
}
