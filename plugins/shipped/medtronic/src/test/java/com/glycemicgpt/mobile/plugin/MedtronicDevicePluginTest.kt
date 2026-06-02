/*
 * AC2 / AC3 / AC5: the MedtronicDevicePlugin exposes the read-only capability contract, maps the
 * lifecycle onto the connection manager, and renders the settings descriptor (status + Unpair +
 * single-peer note) -- all without any write/PUMP_CONTROL surface.
 */
package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.ble.connection.MedtronicBleConnectionManager
import com.glycemicgpt.mobile.ble.read.MedtronicReadGateway
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.model.DiscoveredDevice
import com.glycemicgpt.mobile.domain.plugin.PLUGIN_API_VERSION
import com.glycemicgpt.mobile.domain.plugin.PluginCapability
import com.glycemicgpt.mobile.domain.plugin.capabilities.BgmSource
import com.glycemicgpt.mobile.domain.plugin.capabilities.GlucoseSource
import com.glycemicgpt.mobile.domain.plugin.capabilities.InsulinSource
import com.glycemicgpt.mobile.domain.plugin.capabilities.PumpStatus
import com.glycemicgpt.mobile.domain.plugin.ui.ButtonStyle
import com.glycemicgpt.mobile.domain.plugin.ui.SettingDescriptor
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MedtronicDevicePluginTest {

    private val connectionManager: MedtronicBleConnectionManager = mockk(relaxed = true)
    private val gateway: MedtronicReadGateway = mockk(relaxed = true)

    private val plugin = MedtronicDevicePlugin(connectionManager, gateway)

    @Test
    fun `declares exactly the three read-only capabilities`() {
        val caps = plugin.capabilities
        assertEquals(3, caps.size)
        assertTrue(caps.contains(PluginCapability.GLUCOSE_SOURCE))
        assertTrue(caps.contains(PluginCapability.INSULIN_SOURCE))
        assertTrue(caps.contains(PluginCapability.PUMP_STATUS))
    }

    @Test
    fun `does not declare BOLUS_CATEGORY_PROVIDER`() {
        assertFalse(plugin.capabilities.contains(PluginCapability.BOLUS_CATEGORY_PROVIDER))
    }

    @Test
    fun `getCapability returns GlucoseSource`() {
        val source = plugin.getCapability(GlucoseSource::class)
        assertNotNull(source)
        assertTrue(source is GlucoseSource)
    }

    @Test
    fun `getCapability returns InsulinSource`() {
        val source = plugin.getCapability(InsulinSource::class)
        assertNotNull(source)
        assertTrue(source is InsulinSource)
    }

    @Test
    fun `getCapability returns PumpStatus`() {
        val status = plugin.getCapability(PumpStatus::class)
        assertNotNull(status)
        assertTrue(status is PumpStatus)
    }

    @Test
    fun `getCapability returns null for an unsupported type`() {
        assertNull(plugin.getCapability(BgmSource::class))
    }

    @Test
    fun `metadata uses the canonical id and protocol name`() {
        assertEquals("com.glycemicgpt.medtronic", plugin.metadata.id)
        assertEquals(PLUGIN_API_VERSION, plugin.metadata.apiVersion)
        assertEquals("Medtronic MiniMed Pump", plugin.metadata.name)
        assertEquals("Medtronic", plugin.metadata.protocolName)
    }

    @Test
    fun `connect starts a session (first-pair when forced)`() {
        plugin.connect(address = "ignored", config = emptyMap())
        verify { connectionManager.startSession(false) }

        plugin.connect(address = "ignored", config = mapOf("forceFirstPair" to "true"))
        verify { connectionManager.startSession(true) }
    }

    @Test
    fun `disconnect delegates to the connection manager`() {
        plugin.disconnect()
        verify { connectionManager.disconnect() }
    }

    @Test
    fun `onActivated reconnects to a paired pump`() {
        plugin.onActivated()
        verify { connectionManager.reconnectIfPaired() }
    }

    @Test
    fun `onDeactivated disconnects but preserves pairing`() {
        plugin.onDeactivated()
        verify { connectionManager.disconnect() }
        verify(exactly = 0) { connectionManager.unpair() }
    }

    @Test
    fun `shutdown fully closes the connection manager`() {
        plugin.shutdown()
        verify { connectionManager.close() }
    }

    @Test
    fun `observeConnectionState exposes the manager state flow`() {
        val state = MutableStateFlow(ConnectionState.CONNECTED)
        every { connectionManager.connectionState } returns state
        assertEquals(ConnectionState.CONNECTED, plugin.observeConnectionState().value)
    }

    @Test
    fun `scan passes through the manager's advertise-and-wait discovery`() = runTest {
        val device = DiscoveredDevice(name = "Mobile 000001", address = "AA:BB", pluginId = "com.glycemicgpt.medtronic")
        every { connectionManager.scan() } returns flowOf(device)
        assertEquals(device, plugin.scan().first())
    }

    @Test
    fun `settings descriptor shows status, the single-peer note, and a destructive Unpair`() {
        every { connectionManager.connectionState } returns MutableStateFlow(ConnectionState.DISCONNECTED)

        val items = plugin.settingsDescriptor().sections.single().items
        val status = items.filterIsInstance<SettingDescriptor.InfoText>().first { it.key == "pairing_status" }
        assertTrue(status.text.contains("DISCONNECTED"))

        val singlePeer = items.filterIsInstance<SettingDescriptor.InfoText>().first { it.key == "single_peer_note" }
        assertTrue(singlePeer.text.contains("one phone at a time"))

        val unpair = items.filterIsInstance<SettingDescriptor.ActionButton>().single()
        assertEquals("unpair", unpair.key)
        assertEquals(ButtonStyle.DESTRUCTIVE, unpair.style)
    }
}
