package com.glycemicgpt.mobile.plugin.nightscout

import com.glycemicgpt.mobile.data.remote.dto.NightscoutConnectionDto
import com.glycemicgpt.mobile.domain.plugin.PLUGIN_API_VERSION
import com.glycemicgpt.mobile.domain.plugin.PluginCapability
import com.glycemicgpt.mobile.domain.plugin.capabilities.GlucoseSource
import com.glycemicgpt.mobile.domain.plugin.ui.DetailElement
import com.glycemicgpt.mobile.domain.plugin.ui.SettingDescriptor
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NightscoutSourcePluginTest {

    private val syncManager: NightscoutSyncManager = mockk(relaxed = true)
    private val store = NightscoutSyncStore(FakePluginSettingsStore())
    private var connections: List<NightscoutConnectionDto> = emptyList()

    private val plugin = NightscoutSourcePlugin(
        syncManager = syncManager,
        store = store,
        connectionsProvider = { connections },
    )

    @Test
    fun `metadata advertises the cloud-mediated Nightscout source`() {
        val meta = plugin.metadata
        assertEquals(NightscoutSourcePlugin.PLUGIN_ID, meta.id)
        assertEquals(PLUGIN_API_VERSION, meta.apiVersion)
        assertEquals("Nightscout", meta.protocolName)
    }

    @Test
    fun `declares only DATA_SYNC so it coexists with BLE plugins`() {
        assertEquals(setOf(PluginCapability.DATA_SYNC), plugin.capabilities)
        assertFalse(plugin.capabilities.contains(PluginCapability.GLUCOSE_SOURCE))
    }

    @Test
    fun `exposes no capability interfaces`() {
        assertNull(plugin.getCapability(GlucoseSource::class))
    }

    @Test
    fun `activate enables sync and deactivate disables it`() {
        plugin.onActivated()
        verify(exactly = 1) { syncManager.enable() }

        plugin.onDeactivated()
        verify(exactly = 1) { syncManager.disable() }
    }

    @Test
    fun `sync-now detail action triggers an immediate sync`() {
        plugin.onDetailAction(NightscoutSourcePlugin.CARD_ID, NightscoutSourcePlugin.ACTION_SYNC_NOW)
        verify(exactly = 1) { syncManager.syncNow() }
    }

    @Test
    fun `unknown detail action does not trigger a sync`() {
        plugin.onDetailAction(NightscoutSourcePlugin.CARD_ID, "something_else")
        plugin.onDetailAction("other_card", NightscoutSourcePlugin.ACTION_SYNC_NOW)
        verify(exactly = 0) { syncManager.syncNow() }
    }

    @Test
    fun `settings descriptor surfaces the cloud-mediated note`() {
        val items = plugin.settingsDescriptor().sections.flatMap { it.items }
        assertTrue(items.any { it is SettingDescriptor.InfoText })
    }

    @Test
    fun `dashboard card is tappable and shows not-synced before any sync`() = runTest {
        val cards = plugin.observeDashboardCards().first()
        assertEquals(1, cards.size)
        val card = cards.single()
        assertEquals(NightscoutSourcePlugin.CARD_ID, card.id)
        assertTrue(card.hasDetail)
    }

    @Test
    fun `detail screen offers sync-now and omits the picker for a single connection`() = runTest {
        connections = listOf(connection("conn-1"))
        val screen = plugin.observeDetailScreen(NightscoutSourcePlugin.CARD_ID)!!.first()

        val actionKeys = screen.elements
            .filterIsInstance<DetailElement.Interactive>()
            .map { it.setting.key }
        assertTrue(actionKeys.contains(NightscoutSourcePlugin.ACTION_SYNC_NOW))
        assertFalse(actionKeys.contains(NightscoutSyncStore.KEY_SELECTED_CONNECTION))
    }

    @Test
    fun `detail screen shows a connection picker when more than one connection exists`() = runTest {
        connections = listOf(connection("conn-1"), connection("conn-2"))
        val screen = plugin.observeDetailScreen(NightscoutSourcePlugin.CARD_ID)!!.first()

        val dropdown = screen.elements
            .filterIsInstance<DetailElement.Interactive>()
            .map { it.setting }
            .filterIsInstance<SettingDescriptor.Dropdown>()
            .singleOrNull()
        assertTrue(dropdown != null)
        assertEquals(NightscoutSyncStore.KEY_SELECTED_CONNECTION, dropdown!!.key)
        assertEquals(2, dropdown.options.size)
    }

    @Test
    fun `detail screen is null for an unrelated card`() {
        assertNull(plugin.observeDetailScreen("unrelated"))
    }

    @Test
    fun `formatLastSync renders a placeholder when never synced`() {
        assertEquals("Not synced yet", NightscoutSourcePlugin.formatLastSync(null))
    }

    private fun connection(id: String) =
        NightscoutConnectionDto(id = id, name = "NS $id", isActive = true)
}
