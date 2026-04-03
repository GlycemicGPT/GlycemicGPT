package com.glycemicgpt.mobile.plugin

import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import com.glycemicgpt.mobile.domain.plugin.PLUGIN_API_VERSION
import com.glycemicgpt.mobile.domain.plugin.PluginSettingsStore
import com.glycemicgpt.mobile.domain.pump.DebugLogger
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import com.glycemicgpt.mobile.domain.plugin.events.PluginEventBus
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.flow.MutableStateFlow
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RestrictedPluginContextTest {

    private val baseContext: Context = mockk(relaxed = true)
    private val settingsStore: PluginSettingsStore = mockk(relaxed = true)
    private val debugLogger: DebugLogger = mockk(relaxed = true)
    private val eventBus: PluginEventBus = mockk(relaxed = true)
    private val safetyLimits = MutableStateFlow(SafetyLimits())

    private fun createContext(pluginId: String = "test.runtime.plugin") =
        RestrictedPluginContext.create(
            baseContext = baseContext,
            pluginId = pluginId,
            settingsStore = settingsStore,
            debugLogger = debugLogger,
            eventBus = eventBus,
            safetyLimits = safetyLimits,
        )

    @Test
    fun `creates PluginContext with correct pluginId`() {
        val ctx = createContext()
        assertEquals("test.runtime.plugin", ctx.pluginId)
    }

    @Test
    fun `creates PluginContext with correct apiVersion`() {
        val ctx = createContext()
        assertEquals(PLUGIN_API_VERSION, ctx.apiVersion)
    }

    @Test
    fun `passes through settingsStore`() {
        val ctx = createContext()
        assertEquals(settingsStore, ctx.settingsStore)
    }

    @Test
    fun `passes through debugLogger`() {
        val ctx = createContext()
        assertEquals(debugLogger, ctx.debugLogger)
    }

    @Test
    fun `passes through eventBus`() {
        val ctx = createContext()
        assertEquals(eventBus, ctx.eventBus)
    }

    @Test
    fun `passes through safetyLimits`() {
        val ctx = createContext()
        assertEquals(safetyLimits, ctx.safetyLimits)
    }

    @Test
    fun `androidContext is RestrictedContext`() {
        val ctx = createContext()
        assertTrue(ctx.androidContext is RestrictedContext)
    }

    // -- RestrictedContext: blocked operations --

    @Test
    fun `RestrictedContext blocks startActivity`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.startActivity(Intent())
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("startActivity"))
    }

    @Test
    fun `RestrictedContext blocks startService`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.startService(Intent())
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("startService"))
    }

    @Test
    fun `RestrictedContext blocks startForegroundService`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.startForegroundService(Intent())
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("startForegroundService"))
    }

    @Test
    fun `RestrictedContext blocks getContentResolver`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.contentResolver
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("getContentResolver"))
    }

    @Test
    fun `RestrictedContext blocks sendBroadcast`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.sendBroadcast(Intent())
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("sendBroadcast"))
    }

    @Test
    fun `RestrictedContext blocks getBaseContext`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.baseContext
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("getBaseContext"))
    }

    @Test
    fun `RestrictedContext getApplicationContext returns self`() {
        val restricted = RestrictedContext(baseContext)
        val appContext = restricted.applicationContext
        assertTrue(appContext === restricted)
    }

    @Test
    fun `RestrictedContext blocks createPackageContext`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.createPackageContext("com.other.app", 0)
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("createPackageContext"))
    }

    // -- RestrictedContext: system service allowlist --

    @Test
    fun `RestrictedContext allows allowlisted system services`() {
        // Verify the allowlist contains hardware services needed for BLE plugins.
        assertTrue(
            "BLUETOOTH_SERVICE must be allowlisted",
            RestrictedContext.ALLOWED_SYSTEM_SERVICES.contains(Context.BLUETOOTH_SERVICE),
        )
        assertTrue(
            "LOCATION_SERVICE must be allowlisted",
            RestrictedContext.ALLOWED_SYSTEM_SERVICES.contains(Context.LOCATION_SERVICE),
        )
        assertTrue(
            "POWER_SERVICE must be allowlisted",
            RestrictedContext.ALLOWED_SYSTEM_SERVICES.contains(Context.POWER_SERVICE),
        )
        // WINDOW_SERVICE should NOT be in the allowlist (overlay risk)
        assertFalse(
            "WINDOW_SERVICE must NOT be allowlisted",
            RestrictedContext.ALLOWED_SYSTEM_SERVICES.contains(Context.WINDOW_SERVICE),
        )
    }

    @Test
    fun `RestrictedContext does not throw for allowlisted system services`() {
        // Verify that allowlisted services pass the allowlist check and don't
        // throw SecurityException. The actual return value depends on the base
        // context (which may return null in unit tests), but the key behavior
        // is that no SecurityException is thrown.
        val restricted = RestrictedContext(baseContext)
        val result = try {
            restricted.getSystemService(Context.BLUETOOTH_SERVICE)
            true // no exception = passed allowlist check
        } catch (_: SecurityException) {
            false // would mean it was blocked
        } catch (_: Exception) {
            true // non-security exceptions are fine (mock delegation issues)
        }
        assertTrue("BLUETOOTH_SERVICE should pass allowlist check", result)
    }

    @Test
    fun `RestrictedContext blocks non-allowlisted system services`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.getSystemService(Context.TELEPHONY_SERVICE)
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("getSystemService"))
    }

    @Test
    fun `RestrictedContext blocks getSharedPreferences`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.getSharedPreferences("test", Context.MODE_PRIVATE)
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("getSharedPreferences"))
    }

    @Test
    fun `RestrictedContext blocks startActivities`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.startActivities(arrayOf(Intent()))
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("startActivities"))
    }

    // -- RestrictedContext: storage-blocking overrides --

    @Test
    fun `RestrictedContext blocks openFileOutput`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.openFileOutput("test.txt", Context.MODE_PRIVATE)
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("openFileOutput"))
    }

    @Test
    fun `RestrictedContext blocks openFileInput`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.openFileInput("test.txt")
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("openFileInput"))
    }

    @Test
    fun `RestrictedContext blocks deleteFile`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.deleteFile("test.txt")
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("deleteFile"))
    }

    @Test
    fun `RestrictedContext blocks getDir`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.getDir("test", Context.MODE_PRIVATE)
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("getDir"))
    }

    @Test
    fun `RestrictedContext blocks getDatabasePath`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.getDatabasePath("test.db")
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("getDatabasePath"))
    }

    @Test
    fun `RestrictedContext blocks openOrCreateDatabase`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.openOrCreateDatabase("test.db", Context.MODE_PRIVATE, null)
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("openOrCreateDatabase"))
    }

    @Test
    fun `RestrictedContext blocks deleteDatabase`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.deleteDatabase("test.db")
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("deleteDatabase"))
    }

    @Test
    fun `RestrictedContext blocks createDeviceProtectedStorageContext`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.createDeviceProtectedStorageContext()
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("createDeviceProtectedStorageContext"))
    }

    @Test
    fun `RestrictedContext blocks stopService`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.stopService(Intent())
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("stopService"))
    }

    @Test
    fun `RestrictedContext blocks bindService`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.bindService(Intent(), mockk(relaxed = true), 0)
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("bindService"))
    }

    @Test
    fun `RestrictedContext blocks sendOrderedBroadcast`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.sendOrderedBroadcast(Intent(), null)
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("sendOrderedBroadcast"))
    }

    @Test
    fun `RestrictedContext blocks registerReceiver`() {
        val restricted = RestrictedContext(baseContext)
        val thrown = try {
            restricted.registerReceiver(null, null)
            null
        } catch (e: SecurityException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("registerReceiver"))
    }

    // -- ScopedCredentialProvider tests --

    private fun mockPrefs(): SharedPreferences {
        val store = mutableMapOf<String, String?>()
        val editor = mockk<SharedPreferences.Editor>(relaxed = true)
        every { editor.putString(any(), any()) } answers {
            store[firstArg()] = secondArg()
            editor
        }
        every { editor.remove(any()) } answers {
            store.remove(firstArg<String>())
            editor
        }

        val prefs = mockk<SharedPreferences>(relaxed = true)
        every { prefs.edit() } returns editor
        every { prefs.getString(any(), any()) } answers {
            store[firstArg()] ?: secondArg()
        }
        every { prefs.contains(any()) } answers {
            store.containsKey(firstArg<String>())
        }
        return prefs
    }

    @Test
    fun `ScopedCredentialProvider saves and retrieves pairing`() {
        val prefs = mockPrefs()
        every { baseContext.getSharedPreferences(any(), any()) } returns prefs

        val provider = ScopedCredentialProvider("test.plugin", baseContext)
        assertFalse(provider.isPaired())
        assertNull(provider.getPairedAddress())

        provider.savePairing("AA:BB:CC:DD:EE:FF", "1234")
        assertTrue(provider.isPaired())
        assertEquals("AA:BB:CC:DD:EE:FF", provider.getPairedAddress())
        assertEquals("1234", provider.getPairingCode())
    }

    @Test
    fun `ScopedCredentialProvider clears pairing`() {
        val prefs = mockPrefs()
        every { baseContext.getSharedPreferences(any(), any()) } returns prefs

        val provider = ScopedCredentialProvider("test.plugin", baseContext)
        provider.savePairing("AA:BB:CC:DD:EE:FF", "1234")
        assertTrue(provider.isPaired())

        provider.clearPairing()
        assertFalse(provider.isPaired())
        assertNull(provider.getPairedAddress())
        assertNull(provider.getPairingCode())
    }

    @Test
    fun `ScopedCredentialProvider saves and retrieves JPAKE credentials`() {
        val prefs = mockPrefs()
        every { baseContext.getSharedPreferences(any(), any()) } returns prefs

        val provider = ScopedCredentialProvider("test.plugin", baseContext)
        assertNull(provider.getJpakeDerivedSecret())
        assertNull(provider.getJpakeServerNonce())

        provider.saveJpakeCredentials("deadbeef", "cafebabe")
        assertEquals("deadbeef", provider.getJpakeDerivedSecret())
        assertEquals("cafebabe", provider.getJpakeServerNonce())
    }

    @Test
    fun `ScopedCredentialProvider clears JPAKE credentials`() {
        val prefs = mockPrefs()
        every { baseContext.getSharedPreferences(any(), any()) } returns prefs

        val provider = ScopedCredentialProvider("test.plugin", baseContext)
        provider.saveJpakeCredentials("deadbeef", "cafebabe")
        provider.clearJpakeCredentials()
        assertNull(provider.getJpakeDerivedSecret())
        assertNull(provider.getJpakeServerNonce())
    }

    @Test
    fun `ScopedCredentialProvider uses plugin-namespaced SharedPreferences`() {
        val prefs = mockPrefs()
        every { baseContext.getSharedPreferences(any(), any()) } returns prefs

        ScopedCredentialProvider("com.example.my-plugin", baseContext)
        // sanitizeId preserves dots, hyphens, underscores (unique-preserving)
        verify { baseContext.getSharedPreferences("plugin_creds_com.example.my-plugin", Context.MODE_PRIVATE) }
    }

    @Test
    fun `sanitizeId preserves dots and hyphens but strips path-unsafe chars`() {
        // Dots and hyphens preserved -- distinct IDs remain distinct
        assertEquals("com.foo.bar-baz", ScopedCredentialProvider.sanitizeId("com.foo.bar-baz"))
        assertEquals("com.foo.bar.baz", ScopedCredentialProvider.sanitizeId("com.foo.bar.baz"))
        assertEquals("simple", ScopedCredentialProvider.sanitizeId("simple"))
        // Path-unsafe characters are stripped
        assertEquals("com.foo_bar", ScopedCredentialProvider.sanitizeId("com.foo/bar"))
        assertEquals("com.foo_bar", ScopedCredentialProvider.sanitizeId("com.foo\\bar"))
    }

    @Test
    fun `sanitizeId handles various path-unsafe characters`() {
        assertEquals("foo_bar", ScopedCredentialProvider.sanitizeId("foo:bar"))
        assertEquals("foo_bar", ScopedCredentialProvider.sanitizeId("foo*bar"))
        assertEquals("foo_bar", ScopedCredentialProvider.sanitizeId("foo?bar"))
        assertEquals("foo_bar", ScopedCredentialProvider.sanitizeId("foo<bar"))
        assertEquals("foo_bar", ScopedCredentialProvider.sanitizeId("foo>bar"))
        assertEquals("foo_bar", ScopedCredentialProvider.sanitizeId("foo|bar"))
    }

    @Test
    fun `sanitizeId handles path traversal sequences`() {
        assertEquals("foo_.._bar", ScopedCredentialProvider.sanitizeId("foo/../bar"))
        assertEquals(".._.._.._.._etc_passwd", ScopedCredentialProvider.sanitizeId("../../../../etc/passwd"))
    }

    @Test
    fun `credentialProvider is ScopedCredentialProvider`() {
        val prefs = mockPrefs()
        every { baseContext.getSharedPreferences(any(), any()) } returns prefs

        val ctx = createContext()
        assertTrue(ctx.credentialProvider is ScopedCredentialProvider)
    }
}
