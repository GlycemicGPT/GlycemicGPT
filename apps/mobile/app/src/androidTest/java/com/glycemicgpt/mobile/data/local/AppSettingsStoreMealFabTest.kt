package com.glycemicgpt.mobile.data.local

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Storage-layer coverage for the draggable meal FAB's persisted position. The ViewModel/UI tests
 * mock [AppSettingsStore], so the real EncryptedSharedPreferences round-trip and the unset-sentinel
 * default -- the load-bearing part of the "position persists per device" guarantee -- live here.
 *
 * Instrumented (needs the real Android keystore): run with `./gradlew :app:connectedDebugAndroidTest`.
 */
@RunWith(AndroidJUnit4::class)
class AppSettingsStoreMealFabTest {

    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private lateinit var store: AppSettingsStore

    @Before
    fun setUp() {
        clearEncryptedPrefs()
        store = AppSettingsStore(context)
    }

    @After
    fun tearDown() {
        clearEncryptedPrefs()
    }

    @Test
    fun mealFabOffset_defaultsToUnset_whenNeverMoved() {
        assertEquals(AppSettingsStore.UNSET_FAB_OFFSET, store.mealFabOffsetXPx)
        assertEquals(AppSettingsStore.UNSET_FAB_OFFSET, store.mealFabOffsetYPx)
    }

    @Test
    fun mealFabOffset_roundTripsThroughEncryptedStorage() {
        store.setMealFabOffset(120, 340)

        assertEquals(120, store.mealFabOffsetXPx)
        assertEquals(340, store.mealFabOffsetYPx)
        // The stored value is visible to another store instance (the per-device persistence contract).
        val reread = AppSettingsStore(context)
        assertEquals(120, reread.mealFabOffsetXPx)
        assertEquals(340, reread.mealFabOffsetYPx)
    }

    @Test
    fun mealFabOffset_keepsAxesDistinct() {
        // Guards against a copy-paste key collision: X and Y must use separate storage keys.
        store.setMealFabOffset(11, 22)

        assertEquals(11, store.mealFabOffsetXPx)
        assertEquals(22, store.mealFabOffsetYPx)
    }

    /** Resets the encrypted settings file so default/round-trip assertions are deterministic. */
    private fun clearEncryptedPrefs() {
        context.deleteSharedPreferences("app_settings_encrypted")
    }
}
