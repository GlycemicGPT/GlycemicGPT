package com.glycemicgpt.mobile.data.local

import com.glycemicgpt.mobile.data.remote.dto.DisplayLabelDto
import com.glycemicgpt.mobile.domain.model.BolusCategory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Tests for [AnalyticsSettingsStore] category label logic.
 *
 * Uses an in-memory mirror to avoid Android SharedPreferences dependency.
 */
class AnalyticsSettingsStoreTest {

    /** Simple in-memory implementation for testing. */
    private class InMemoryAnalyticsStore {
        var dayBoundaryHour: Int = 0
        var categoryLabels: Map<String, String> = emptyMap()
        var lastFetchedMs: Long = 0L

        fun labelFor(category: BolusCategory): String =
            categoryLabels[category.name] ?: category.displayName

        fun updateAll(hour: Int, labels: Map<String, String>? = null) {
            require(hour in 0..23)
            dayBoundaryHour = hour
            lastFetchedMs = System.currentTimeMillis()
            if (labels != null) {
                categoryLabels = labels
            }
        }

        fun updateCategoryLabels(labels: Map<String, String>) {
            categoryLabels = labels
            lastFetchedMs = System.currentTimeMillis()
        }

        fun isStale(maxAgeMs: Long = 900_000L): Boolean {
            val age = System.currentTimeMillis() - lastFetchedMs
            return age > maxAgeMs
        }

        fun clear() {
            dayBoundaryHour = 0
            categoryLabels = emptyMap()
            lastFetchedMs = 0L
        }
    }

    @Test
    fun `labelFor returns custom label when present`() {
        val store = InMemoryAnalyticsStore()
        store.updateCategoryLabels(mapOf("FOOD" to "Meal Bolus"))
        assertEquals("Meal Bolus", store.labelFor(BolusCategory.FOOD))
    }

    @Test
    fun `labelFor falls back to displayName when no custom label`() {
        val store = InMemoryAnalyticsStore()
        assertEquals("Meal", store.labelFor(BolusCategory.FOOD))
    }

    @Test
    fun `labelFor falls back for all categories when empty`() {
        val store = InMemoryAnalyticsStore()
        for (cat in BolusCategory.entries) {
            assertEquals(cat.displayName, store.labelFor(cat))
        }
    }

    @Test
    fun `updateAll with labels persists both hour and labels`() {
        val store = InMemoryAnalyticsStore()
        val labels = mapOf("AUTO_CORRECTION" to "Auto", "FOOD" to "Food Dose")
        store.updateAll(6, labels)
        assertEquals(6, store.dayBoundaryHour)
        assertEquals("Auto", store.categoryLabels["AUTO_CORRECTION"])
        assertEquals("Food Dose", store.categoryLabels["FOOD"])
    }

    @Test
    fun `updateAll without labels preserves existing labels`() {
        val store = InMemoryAnalyticsStore()
        store.updateCategoryLabels(mapOf("FOOD" to "Meal"))
        store.updateAll(12)
        assertEquals(12, store.dayBoundaryHour)
        assertEquals("Meal", store.categoryLabels["FOOD"])
    }

    @Test
    fun `updateCategoryLabels replaces all labels`() {
        val store = InMemoryAnalyticsStore()
        store.updateCategoryLabels(mapOf("FOOD" to "A"))
        store.updateCategoryLabels(mapOf("CORRECTION" to "B"))
        // "FOOD" was replaced when new map was set
        assertEquals(null, store.categoryLabels["FOOD"])
        assertEquals("B", store.categoryLabels["CORRECTION"])
    }

    @Test
    fun `clear resets all fields`() {
        val store = InMemoryAnalyticsStore()
        store.updateAll(8, mapOf("FOOD" to "Test"))
        store.clear()
        assertEquals(0, store.dayBoundaryHour)
        assertTrue(store.categoryLabels.isEmpty())
        assertEquals(0L, store.lastFetchedMs)
    }

    @Test
    fun `isStale returns true when never fetched`() {
        val store = InMemoryAnalyticsStore()
        assertTrue(store.isStale())
    }

    @Test
    fun `boundary hour validation rejects out of range`() {
        val store = InMemoryAnalyticsStore()
        var thrown = false
        try {
            store.updateAll(-1)
        } catch (_: IllegalArgumentException) {
            thrown = true
        }
        assertTrue("Expected exception for hour=-1", thrown)

        thrown = false
        try {
            store.updateAll(24)
        } catch (_: IllegalArgumentException) {
            thrown = true
        }
        assertTrue("Expected exception for hour=24", thrown)
    }

    // -- displayLabelsToMap tests --

    @Test
    fun `displayLabelsToMap converts labels with roles`() {
        val labels = listOf(
            DisplayLabelDto(id = "meal", label = "My Meals", computationRole = "FOOD", sortOrder = 0),
            DisplayLabelDto(id = "corr", label = "Fixes", computationRole = "CORRECTION", sortOrder = 1),
            DisplayLabelDto(id = "custom", label = "Custom", computationRole = null, sortOrder = 2),
        )
        val result = AnalyticsSettingsStore.displayLabelsToMap(labels, null)!!
        assertEquals("My Meals", result["FOOD"])
        assertEquals("Fixes", result["CORRECTION"])
        assertNull(result["custom"]) // no computation_role -> excluded
        assertEquals(2, result.size)
    }

    @Test
    fun `displayLabelsToMap falls back to categoryLabels when displayLabels is null`() {
        val fallback = mapOf("FOOD" to "Meal")
        val result = AnalyticsSettingsStore.displayLabelsToMap(null, fallback)
        assertEquals(fallback, result)
    }

    @Test
    fun `displayLabelsToMap falls back when displayLabels is empty`() {
        val fallback = mapOf("FOOD" to "Meal")
        val result = AnalyticsSettingsStore.displayLabelsToMap(emptyList(), fallback)
        assertEquals(fallback, result)
    }

    @Test
    fun `displayLabelsToMap returns null when both are null`() {
        val result = AnalyticsSettingsStore.displayLabelsToMap(null, null)
        assertNull(result)
    }
}
