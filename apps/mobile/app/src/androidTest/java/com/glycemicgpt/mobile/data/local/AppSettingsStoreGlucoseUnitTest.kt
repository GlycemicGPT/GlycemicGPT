package com.glycemicgpt.mobile.data.local

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.glycemicgpt.mobile.domain.model.GlucoseUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Storage-layer coverage for the per-account glucose display unit. The ViewModel tests mock
 * [AppSettingsStore], so the real EncryptedSharedPreferences round-trip and the reactive
 * [AppSettingsStore.glucoseUnitFlow] live here.
 *
 * The flow case is load-bearing: the dashboard re-renders glucose surfaces the instant the unit
 * changes by collecting [AppSettingsStore.glucoseUnitFlow], which only re-emits if the encrypted
 * prefs change listener reports the *plaintext* key. This pins that contract -- a security-crypto
 * change that started delivering encrypted keys would fail here instead of silently freezing the UI.
 *
 * Instrumented (needs the real Android keystore): run with `./gradlew :app:connectedDebugAndroidTest`.
 */
@RunWith(AndroidJUnit4::class)
class AppSettingsStoreGlucoseUnitTest {

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
    fun glucoseUnit_defaultsToMgdl_whenUnset() {
        assertEquals(GlucoseUnit.MGDL, store.glucoseUnit)
    }

    @Test
    fun glucoseUnit_roundTripsThroughEncryptedStorage() {
        store.glucoseUnit = GlucoseUnit.MMOL

        assertEquals(GlucoseUnit.MMOL, store.glucoseUnit)
        // The stored value is visible to another store instance (the per-account singleton contract).
        assertEquals(GlucoseUnit.MMOL, AppSettingsStore(context).glucoseUnit)
    }

    @Test
    fun glucoseUnitFlow_emitsCurrentValueThenReEmitsAfterChange() = runBlocking {
        store.glucoseUnit = GlucoseUnit.MGDL
        val emissions = Channel<GlucoseUnit>(Channel.UNLIMITED)
        val collector = launch(Dispatchers.Default) {
            store.glucoseUnitFlow().collect { emissions.send(it) }
        }
        try {
            // Seed emission also confirms the collector has subscribed.
            assertEquals(GlucoseUnit.MGDL, withTimeout(TIMEOUT_MS) { emissions.receive() })
            // The change listener is registered right after the seed (no suspension point between
            // the two in the callbackFlow body); a short grace lets that registration win the race
            // against the write under any scheduling.
            delay(REGISTRATION_GRACE_MS)
            store.glucoseUnit = GlucoseUnit.MMOL
            // Drain to the post-write value instead of asserting the very next emission, so a
            // duplicate (e.g. a key == null listener fire) can't flip the result. The timeout is
            // the real failsafe if the listener never re-emits.
            val reEmitted = withTimeout(TIMEOUT_MS) {
                var value = emissions.receive()
                while (value != GlucoseUnit.MMOL) value = emissions.receive()
                value
            }
            assertEquals(GlucoseUnit.MMOL, reEmitted)
        } finally {
            collector.cancel()
        }
    }

    /** Resets the encrypted settings file so default/round-trip assertions are deterministic. */
    private fun clearEncryptedPrefs() {
        // The file name is the storage contract (mirrors AppSettingsStore's private
        // ENCRYPTED_PREFS_NAME); deleting it returns the store to a pristine state between tests.
        context.deleteSharedPreferences("app_settings_encrypted")
    }

    private companion object {
        const val TIMEOUT_MS = 5_000L
        const val REGISTRATION_GRACE_MS = 250L
    }
}
