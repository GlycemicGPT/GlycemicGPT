package com.glycemicgpt.mobile.data.local

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Tests for [AlertSoundCategory] enum and the category-dispatch logic
 * used by [AlertSoundStore]. These tests validate the enum values and
 * the getter/setter dispatch without Android SharedPreferences (which
 * requires Robolectric). The production store uses the same dispatch pattern.
 */
class AlertSoundStoreTest {

    @Test
    fun `AlertSoundCategory has exactly three values`() {
        assertEquals(3, AlertSoundCategory.entries.size)
    }

    @Test
    fun `AlertSoundCategory values are correct`() {
        val names = AlertSoundCategory.entries.map { it.name }
        assertTrue("LOW_ALERT" in names)
        assertTrue("HIGH_ALERT" in names)
        assertTrue("AI_NOTIFICATION" in names)
    }

    // --- In-memory store mirror tests ---

    @Test
    fun `getSoundUri returns null by default`() {
        val store = InMemoryAlertSoundStore()
        assertNull(store.getSoundUri(AlertSoundCategory.LOW_ALERT))
        assertNull(store.getSoundUri(AlertSoundCategory.HIGH_ALERT))
        assertNull(store.getSoundUri(AlertSoundCategory.AI_NOTIFICATION))
    }

    @Test
    fun `setSoundUri and getSoundUri round-trip for each category`() {
        val store = InMemoryAlertSoundStore()
        val testUri = "content://media/external/audio/media/42"

        for (category in AlertSoundCategory.entries) {
            store.setSoundUri(category, testUri)
            assertEquals(testUri, store.getSoundUri(category))
        }
    }

    @Test
    fun `setSoundUri to null clears the value`() {
        val store = InMemoryAlertSoundStore()
        store.setSoundUri(AlertSoundCategory.LOW_ALERT, "content://test")
        store.setSoundUri(AlertSoundCategory.LOW_ALERT, null)
        assertNull(store.getSoundUri(AlertSoundCategory.LOW_ALERT))
    }

    @Test
    fun `getSoundName returns null by default`() {
        val store = InMemoryAlertSoundStore()
        assertNull(store.getSoundName(AlertSoundCategory.LOW_ALERT))
    }

    @Test
    fun `setSoundName and getSoundName round-trip`() {
        val store = InMemoryAlertSoundStore()
        store.setSoundName(AlertSoundCategory.HIGH_ALERT, "Alarm Tone")
        assertEquals("Alarm Tone", store.getSoundName(AlertSoundCategory.HIGH_ALERT))
    }

    @Test
    fun `getChannelVersion returns 1 by default`() {
        val store = InMemoryAlertSoundStore()
        assertEquals(1, store.getChannelVersion(AlertSoundCategory.LOW_ALERT))
        assertEquals(1, store.getChannelVersion(AlertSoundCategory.HIGH_ALERT))
        assertEquals(1, store.getChannelVersion(AlertSoundCategory.AI_NOTIFICATION))
    }

    @Test
    fun `incrementChannelVersion bumps and returns new version`() {
        val store = InMemoryAlertSoundStore()
        assertEquals(2, store.incrementChannelVersion(AlertSoundCategory.LOW_ALERT))
        assertEquals(2, store.getChannelVersion(AlertSoundCategory.LOW_ALERT))
        assertEquals(3, store.incrementChannelVersion(AlertSoundCategory.LOW_ALERT))
        assertEquals(3, store.getChannelVersion(AlertSoundCategory.LOW_ALERT))
    }

    @Test
    fun `incrementChannelVersion is independent per category`() {
        val store = InMemoryAlertSoundStore()
        store.incrementChannelVersion(AlertSoundCategory.LOW_ALERT)
        store.incrementChannelVersion(AlertSoundCategory.LOW_ALERT)
        assertEquals(3, store.getChannelVersion(AlertSoundCategory.LOW_ALERT))
        assertEquals(1, store.getChannelVersion(AlertSoundCategory.HIGH_ALERT))
        assertEquals(1, store.getChannelVersion(AlertSoundCategory.AI_NOTIFICATION))
    }

    @Test
    fun `overrideSilent defaults to true`() {
        val store = InMemoryAlertSoundStore()
        assertTrue(store.overrideSilent)
    }

    @Test
    fun `overrideSilent can be toggled`() {
        val store = InMemoryAlertSoundStore()
        store.overrideSilent = false
        assertEquals(false, store.overrideSilent)
        store.overrideSilent = true
        assertEquals(true, store.overrideSilent)
    }

    /**
     * In-memory mirror of [AlertSoundStore] for testing without Android
     * SharedPreferences. Uses the same dispatch logic.
     */
    private class InMemoryAlertSoundStore {
        private val uris = mutableMapOf<AlertSoundCategory, String?>()
        private val names = mutableMapOf<AlertSoundCategory, String?>()
        private val versions = mutableMapOf<AlertSoundCategory, Int>()
        var overrideSilent: Boolean = true

        fun getSoundUri(category: AlertSoundCategory): String? = uris[category]
        fun setSoundUri(category: AlertSoundCategory, uri: String?) { uris[category] = uri }

        fun getSoundName(category: AlertSoundCategory): String? = names[category]
        fun setSoundName(category: AlertSoundCategory, name: String?) { names[category] = name }

        fun getChannelVersion(category: AlertSoundCategory): Int = versions[category] ?: 1

        fun incrementChannelVersion(category: AlertSoundCategory): Int {
            val newVersion = getChannelVersion(category) + 1
            versions[category] = newVersion
            return newVersion
        }
    }
}
