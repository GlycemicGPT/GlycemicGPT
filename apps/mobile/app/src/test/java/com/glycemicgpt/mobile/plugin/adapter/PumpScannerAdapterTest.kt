package com.glycemicgpt.mobile.plugin.adapter

import app.cash.turbine.test
import com.glycemicgpt.mobile.domain.model.DiscoveredDevice
import com.glycemicgpt.mobile.domain.plugin.DevicePlugin
import com.glycemicgpt.mobile.plugin.PluginRegistry
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test

class PumpScannerAdapterTest {

    private val registry: PluginRegistry = mockk(relaxed = true)

    @Test
    fun `scan delegates to active plugin`() = runTest {
        val device = DiscoveredDevice(
            name = "Tandem X2",
            address = "AA:BB:CC:DD:EE:FF",
            rssi = -50,
            pluginId = "com.glycemicgpt.tandem",
        )
        val plugin: DevicePlugin = mockk(relaxed = true) {
            every { scan() } returns flowOf(device)
        }
        every { registry.activePumpPlugin } returns MutableStateFlow(plugin)

        val adapter = PumpScannerAdapter(registry)

        adapter.scan().test {
            val result = awaitItem()
            assertEquals("Tandem X2", result.name)
            assertEquals("AA:BB:CC:DD:EE:FF", result.address)
            assertEquals(-50, result.rssi)
            awaitComplete()
        }
    }

    @Test
    fun `scan returns empty flow when no active plugin`() = runTest {
        every { registry.activePumpPlugin } returns MutableStateFlow(null)

        val adapter = PumpScannerAdapter(registry)

        adapter.scan().test {
            awaitComplete()
        }
    }
}
