package com.glycemicgpt.mobile.plugin

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TandemBolusCategoryProviderTest {

    private val provider = TandemBolusCategoryProvider()

    @Test
    fun `declaredCategories returns all 7 Tandem categories`() {
        val categories = provider.declaredCategories()
        assertEquals(7, categories.size)
        assert(categories.contains(TandemBolusCategoryProvider.CONTROL_IQ))
        assert(categories.contains(TandemBolusCategoryProvider.BG_FOOD))
        assert(categories.contains(TandemBolusCategoryProvider.BG_ONLY))
        assert(categories.contains(TandemBolusCategoryProvider.FOOD_ONLY))
        assert(categories.contains(TandemBolusCategoryProvider.OVERRIDE))
        assert(categories.contains(TandemBolusCategoryProvider.QUICK))
        assert(categories.contains(TandemBolusCategoryProvider.UNKNOWN))
    }

    @Test
    fun `all declared categories map to a platform category`() {
        for (category in provider.declaredCategories()) {
            assertNotNull(
                "Category '$category' should map to a platform category",
                provider.toPlatformCategory(category),
            )
        }
    }

    @Test
    fun `CONTROL_IQ maps to AUTO_CORRECTION`() {
        assertEquals("AUTO_CORRECTION", provider.toPlatformCategory(TandemBolusCategoryProvider.CONTROL_IQ))
    }

    @Test
    fun `BG_FOOD maps to FOOD_AND_CORRECTION`() {
        assertEquals("FOOD_AND_CORRECTION", provider.toPlatformCategory(TandemBolusCategoryProvider.BG_FOOD))
    }

    @Test
    fun `BG_ONLY maps to CORRECTION`() {
        assertEquals("CORRECTION", provider.toPlatformCategory(TandemBolusCategoryProvider.BG_ONLY))
    }

    @Test
    fun `FOOD_ONLY maps to FOOD`() {
        assertEquals("FOOD", provider.toPlatformCategory(TandemBolusCategoryProvider.FOOD_ONLY))
    }

    @Test
    fun `OVERRIDE maps to OVERRIDE`() {
        assertEquals("OVERRIDE", provider.toPlatformCategory(TandemBolusCategoryProvider.OVERRIDE))
    }

    @Test
    fun `QUICK maps to OTHER`() {
        assertEquals("OTHER", provider.toPlatformCategory(TandemBolusCategoryProvider.QUICK))
    }

    @Test
    fun `unknown category returns null`() {
        assertNull(provider.toPlatformCategory("NONEXISTENT"))
    }

    @Test
    fun `all mapped platform names are valid known category names`() {
        // These must match BolusCategory enum names in the app module.
        // If a mapping is wrong, the app's BolusCategoryMapper.resolve() will
        // silently fall back to OTHER, which is incorrect behavior.
        val validPlatformNames = setOf(
            "AUTO_CORRECTION", "FOOD", "FOOD_AND_CORRECTION", "CORRECTION",
            "OVERRIDE", "AI_SUGGESTED", "OTHER",
        )
        for (category in provider.declaredCategories()) {
            val platformName = provider.toPlatformCategory(category)!!
            assertTrue(
                "Platform name '$platformName' for '$category' must be a valid BolusCategory name",
                validPlatformNames.contains(platformName),
            )
        }
    }
}
