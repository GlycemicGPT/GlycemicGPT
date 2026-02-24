package com.glycemicgpt.mobile.plugin

import android.content.Context
import app.cash.turbine.test
import com.glycemicgpt.mobile.data.local.SafetyLimitsStore
import com.glycemicgpt.mobile.domain.plugin.DevicePlugin
import com.glycemicgpt.mobile.domain.plugin.PLUGIN_API_VERSION
import com.glycemicgpt.mobile.domain.plugin.Plugin
import com.glycemicgpt.mobile.domain.plugin.PluginCapability
import com.glycemicgpt.mobile.domain.plugin.PluginContext
import com.glycemicgpt.mobile.domain.plugin.PluginFactory
import com.glycemicgpt.mobile.domain.plugin.PluginMetadata
import com.glycemicgpt.mobile.domain.pump.DebugLogger
import com.glycemicgpt.mobile.domain.plugin.events.PluginEvent
import com.glycemicgpt.mobile.domain.pump.PumpCredentialProvider
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class PluginRegistryTest {

    private val context: Context = mockk(relaxed = true)
    private val preferences: PluginPreferences = mockk(relaxed = true)
    private val eventBus: PluginEventBusImpl = mockk(relaxed = true)
    private val credentialProvider: PumpCredentialProvider = mockk(relaxed = true)
    private val debugLogger: DebugLogger = mockk(relaxed = true)
    private val safetyLimitsStore: SafetyLimitsStore = mockk {
        every { toSafetyLimits() } returns SafetyLimits()
    }

    private fun createPlugin(
        id: String,
        capabilities: Set<PluginCapability> = emptySet(),
    ): Plugin = mockk(relaxed = true) {
        every { metadata } returns PluginMetadata(
            id = id,
            name = "Test Plugin $id",
            version = "1.0.0",
            apiVersion = PLUGIN_API_VERSION,
        )
        every { this@mockk.capabilities } returns capabilities
    }

    private fun createFactory(
        plugin: Plugin,
        apiVersion: Int = PLUGIN_API_VERSION,
    ): PluginFactory {
        val meta = plugin.metadata.copy(apiVersion = apiVersion)
        return mockk {
            every { metadata } returns meta
            every { create(any()) } returns plugin
        }
    }

    private fun createRegistry(factories: Set<PluginFactory>): PluginRegistry =
        PluginRegistry(
            factories = factories,
            preferences = preferences,
            eventBus = eventBus,
            context = context,
            credentialProvider = credentialProvider,
            debugLogger = debugLogger,
            safetyLimitsStore = safetyLimitsStore,
        )

    @Before
    fun setUp() {
        // Default: no previously active plugins
        every { preferences.getActivePluginId(any()) } returns null
        every { preferences.getActivePluginIds(any()) } returns emptySet()
    }

    @Test
    fun `initialize creates plugins from factories`() {
        val plugin = createPlugin("test.plugin.1")
        val factory = createFactory(plugin)
        val registry = createRegistry(setOf(factory))

        registry.initialize()

        verify { factory.create(any()) }
        verify { plugin.initialize(any()) }
        assertEquals(1, registry.availablePlugins.value.size)
        assertEquals("test.plugin.1", registry.availablePlugins.value[0].id)
    }

    @Test
    fun `activatePlugin activates and updates state flows`() {
        val plugin: DevicePlugin = mockk(relaxed = true) {
            every { metadata } returns PluginMetadata(
                id = "test.pump",
                name = "Test Pump",
                version = "1.0.0",
                apiVersion = PLUGIN_API_VERSION,
            )
            every { capabilities } returns setOf(
                PluginCapability.GLUCOSE_SOURCE,
                PluginCapability.INSULIN_SOURCE,
                PluginCapability.PUMP_STATUS,
            )
        }
        val factory = createFactory(plugin)
        val registry = createRegistry(setOf(factory))
        registry.initialize()

        val result = registry.activatePlugin("test.pump")

        assertTrue(result.isSuccess)
        verify { plugin.onActivated() }
        assertNotNull(registry.activePumpPlugin.value)
        assertNotNull(registry.activeGlucoseSource.value)
        assertEquals(1, registry.allActivePlugins.value.size)
    }

    @Test
    fun `activatePlugin with conflicting capability deactivates old plugin`() {
        val oldPlugin: DevicePlugin = mockk(relaxed = true) {
            every { metadata } returns PluginMetadata(
                id = "old.pump",
                name = "Old Pump",
                version = "1.0.0",
                apiVersion = PLUGIN_API_VERSION,
            )
            every { capabilities } returns setOf(PluginCapability.GLUCOSE_SOURCE)
        }
        val newPlugin: DevicePlugin = mockk(relaxed = true) {
            every { metadata } returns PluginMetadata(
                id = "new.pump",
                name = "New Pump",
                version = "1.0.0",
                apiVersion = PLUGIN_API_VERSION,
            )
            every { capabilities } returns setOf(PluginCapability.GLUCOSE_SOURCE)
        }
        val oldFactory = createFactory(oldPlugin)
        val newFactory = createFactory(newPlugin)

        // When the new plugin checks for existing GLUCOSE_SOURCE, return old plugin
        every { preferences.getActivePluginId(PluginCapability.GLUCOSE_SOURCE) } returns "old.pump"

        val registry = createRegistry(setOf(oldFactory, newFactory))
        registry.initialize()

        // Activate old first
        registry.activatePlugin("old.pump")

        // Now activate new -- should deactivate old
        val result = registry.activatePlugin("new.pump")

        assertTrue(result.isSuccess)
        verify { oldPlugin.onDeactivated() }
        verify { newPlugin.onActivated() }
    }

    @Test
    fun `deactivatePlugin removes from active and clears preferences`() {
        val plugin = createPlugin(
            "test.plugin",
            capabilities = setOf(PluginCapability.GLUCOSE_SOURCE),
        )
        val factory = createFactory(plugin)
        val registry = createRegistry(setOf(factory))
        registry.initialize()
        registry.activatePlugin("test.plugin")

        // Mock that this plugin is persisted as active
        every {
            preferences.getActivePluginId(PluginCapability.GLUCOSE_SOURCE)
        } returns "test.plugin"

        val result = registry.deactivatePlugin("test.plugin")

        assertTrue(result.isSuccess)
        verify { plugin.onDeactivated() }
        verify { preferences.clearActivePlugin(PluginCapability.GLUCOSE_SOURCE) }
        assertEquals(0, registry.allActivePlugins.value.size)
    }

    @Test
    fun `activatePlugin with wrong API version skips plugin`() {
        val plugin = createPlugin("bad.version")
        val factory = createFactory(plugin, apiVersion = PLUGIN_API_VERSION + 1)
        val registry = createRegistry(setOf(factory))

        registry.initialize()

        // Plugin should not be registered since API version doesn't match
        assertEquals(0, registry.availablePlugins.value.size)
        assertTrue(registry.activatePlugin("bad.version").isFailure)
    }

    @Test
    fun `getPlugin returns plugin by id`() {
        val plugin = createPlugin("test.plugin.get")
        val factory = createFactory(plugin)
        val registry = createRegistry(setOf(factory))
        registry.initialize()

        val result = registry.getPlugin("test.plugin.get")

        assertNotNull(result)
        assertEquals("test.plugin.get", result!!.metadata.id)
    }

    @Test
    fun `getPlugin returns null for unknown id`() {
        val registry = createRegistry(emptySet())
        registry.initialize()

        val result = registry.getPlugin("nonexistent.plugin")

        assertNull(result)
    }

    @Test
    fun `refreshSafetyLimits updates StateFlow and publishes event`() = runTest {
        val updatedLimits = SafetyLimits.safeOf(
            minGlucoseMgDl = 50,
            maxGlucoseMgDl = 450,
            maxBasalRateMilliunits = 3000,
            maxBolusDoseMilliunits = 20000,
        )
        // Use a fresh mock so returnsMany starts from call #1
        val localStore: SafetyLimitsStore = mockk {
            every { toSafetyLimits() } returnsMany listOf(
                SafetyLimits(), // constructor
                updatedLimits,  // refreshSafetyLimits()
            )
        }

        val realEventBus = PluginEventBusImpl()

        val registry = PluginRegistry(
            factories = emptySet(),
            preferences = preferences,
            eventBus = realEventBus,
            context = context,
            credentialProvider = credentialProvider,
            debugLogger = debugLogger,
            safetyLimitsStore = localStore,
        )
        registry.initialize()

        // Subscribe with Turbine, then trigger refresh
        realEventBus.subscribe(PluginEvent.SafetyLimitsChanged::class).test {
            registry.refreshSafetyLimits()

            val event = awaitItem()
            assertEquals(PluginRegistry.PLATFORM_PLUGIN_ID, event.pluginId)
            assertEquals(updatedLimits, event.limits)
        }
    }

    @Test
    fun `initialize cannot be called twice`() {
        val registry = createRegistry(emptySet())
        registry.initialize()

        val thrown = try {
            registry.initialize()
            null
        } catch (e: IllegalStateException) {
            e
        }
        assertNotNull(thrown)
    }
}
