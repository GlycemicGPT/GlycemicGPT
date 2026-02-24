package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.ble.connection.BleConnectionManager
import com.glycemicgpt.mobile.ble.connection.BleScanner
import com.glycemicgpt.mobile.ble.connection.TandemBleDriver
import com.glycemicgpt.mobile.ble.messages.TandemHistoryLogParser
import com.glycemicgpt.mobile.domain.plugin.PLUGIN_API_VERSION
import com.glycemicgpt.mobile.domain.plugin.PluginCapability
import com.glycemicgpt.mobile.domain.plugin.capabilities.GlucoseSource
import com.glycemicgpt.mobile.domain.plugin.capabilities.InsulinSource
import com.glycemicgpt.mobile.domain.plugin.capabilities.PumpStatus
import io.mockk.mockk
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TandemDevicePluginTest {

    private val connectionManager: BleConnectionManager = mockk(relaxed = true)
    private val bleDriver: TandemBleDriver = mockk(relaxed = true)
    private val scanner: BleScanner = mockk(relaxed = true)
    private val historyParser: TandemHistoryLogParser = mockk(relaxed = true)

    private val plugin = TandemDevicePlugin(
        connectionManager = connectionManager,
        bleDriver = bleDriver,
        scanner = scanner,
        historyParser = historyParser,
    )

    @Test
    fun `capabilities includes GLUCOSE_SOURCE, INSULIN_SOURCE, PUMP_STATUS`() {
        val caps = plugin.capabilities
        assertEquals(3, caps.size)
        assertTrue(caps.contains(PluginCapability.GLUCOSE_SOURCE))
        assertTrue(caps.contains(PluginCapability.INSULIN_SOURCE))
        assertTrue(caps.contains(PluginCapability.PUMP_STATUS))
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
    fun `getCapability returns null for unsupported type`() {
        val result = plugin.getCapability(
            com.glycemicgpt.mobile.domain.plugin.capabilities.BgmSource::class,
        )
        assertNull(result)
    }

    @Test
    fun `metadata has correct plugin id`() {
        assertEquals("com.glycemicgpt.tandem", plugin.metadata.id)
        assertEquals(PLUGIN_API_VERSION, plugin.metadata.apiVersion)
        assertEquals("Tandem t:slim X2", plugin.metadata.name)
    }
}
