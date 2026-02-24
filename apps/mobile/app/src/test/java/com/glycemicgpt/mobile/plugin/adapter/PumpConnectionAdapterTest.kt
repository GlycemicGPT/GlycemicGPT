package com.glycemicgpt.mobile.plugin.adapter

import app.cash.turbine.test
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.plugin.DevicePlugin
import com.glycemicgpt.mobile.plugin.PluginRegistry
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PumpConnectionAdapterTest {

    private val testDispatcher = UnconfinedTestDispatcher()
    private val pluginFlow = MutableStateFlow<DevicePlugin?>(null)
    private val registry: PluginRegistry = mockk(relaxed = true) {
        every { activePumpPlugin } returns pluginFlow
    }

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `connectionState follows active plugin`() = runTest {
        val connectionFlow = MutableStateFlow(ConnectionState.DISCONNECTED)
        val plugin: DevicePlugin = mockk(relaxed = true) {
            every { observeConnectionState() } returns connectionFlow
        }
        pluginFlow.value = plugin

        val adapter = PumpConnectionAdapter(registry)

        adapter.connectionState.test {
            assertEquals(ConnectionState.DISCONNECTED, awaitItem())

            connectionFlow.value = ConnectionState.CONNECTED
            assertEquals(ConnectionState.CONNECTED, awaitItem())
        }
    }

    @Test
    fun `connect delegates to active plugin`() {
        val plugin: DevicePlugin = mockk(relaxed = true)
        pluginFlow.value = plugin

        val adapter = PumpConnectionAdapter(registry)
        adapter.connect("AA:BB:CC:DD:EE:FF", "123456")

        verify { plugin.connect("AA:BB:CC:DD:EE:FF", mapOf("pairingCode" to "123456")) }
    }

    @Test
    fun `connect does nothing when no active plugin`() {
        pluginFlow.value = null

        val adapter = PumpConnectionAdapter(registry)
        // Should not throw
        adapter.connect("AA:BB:CC:DD:EE:FF", null)
    }
}
