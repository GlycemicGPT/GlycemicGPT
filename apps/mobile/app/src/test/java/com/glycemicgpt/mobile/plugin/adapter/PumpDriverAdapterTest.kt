package com.glycemicgpt.mobile.plugin.adapter

import app.cash.turbine.test
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.plugin.DevicePlugin
import com.glycemicgpt.mobile.domain.plugin.capabilities.GlucoseSource
import com.glycemicgpt.mobile.domain.plugin.capabilities.InsulinSource
import com.glycemicgpt.mobile.plugin.PluginRegistry
import io.mockk.coEvery
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

class PumpDriverAdapterTest {

    private val pumpPluginFlow = MutableStateFlow<DevicePlugin?>(null)
    private val glucosePluginFlow = MutableStateFlow<DevicePlugin?>(null)
    private val registry: PluginRegistry = mockk(relaxed = true) {
        every { activePumpPlugin } returns pumpPluginFlow
        every { activeGlucoseSource } returns glucosePluginFlow
    }
    private val adapter = PumpDriverAdapter(registry)

    @Test
    fun `getIoB delegates to active plugin insulin source`() = runTest {
        val expected = IoBReading(iob = 2.5f, timestamp = Instant.now())
        val insulinSource: InsulinSource = mockk {
            coEvery { getIoB() } returns Result.success(expected)
        }
        val plugin: DevicePlugin = mockk(relaxed = true) {
            every { getCapability(InsulinSource::class) } returns insulinSource
        }
        pumpPluginFlow.value = plugin

        val result = adapter.getIoB()

        assertTrue(result.isSuccess)
        assertEquals(expected, result.getOrThrow())
    }

    @Test
    fun `getIoB returns failure when no active plugin`() = runTest {
        pumpPluginFlow.value = null

        val result = adapter.getIoB()

        assertTrue(result.isFailure)
        assertTrue(result.exceptionOrNull() is NoActivePluginException)
    }

    @Test
    fun `getCgmStatus delegates to active glucose source`() = runTest {
        val expected = CgmReading(
            glucoseMgDl = 120,
            trendArrow = CgmTrend.FLAT,
            timestamp = Instant.now(),
        )
        val glucoseSource: GlucoseSource = mockk {
            coEvery { getCurrentReading() } returns Result.success(expected)
        }
        val plugin: DevicePlugin = mockk(relaxed = true) {
            every { getCapability(GlucoseSource::class) } returns glucoseSource
        }
        glucosePluginFlow.value = plugin

        val result = adapter.getCgmStatus()

        assertTrue(result.isSuccess)
        assertEquals(expected, result.getOrThrow())
    }

    @Test
    fun `getCgmStatus returns failure when no active glucose plugin`() = runTest {
        glucosePluginFlow.value = null

        val result = adapter.getCgmStatus()

        assertTrue(result.isFailure)
        assertTrue(result.exceptionOrNull() is NoActivePluginException)
    }

    @Test
    fun `observeConnectionState follows active plugin`() = runTest {
        val connectionFlow = MutableStateFlow(ConnectionState.DISCONNECTED)
        val plugin: DevicePlugin = mockk(relaxed = true) {
            every { observeConnectionState() } returns connectionFlow
        }

        adapter.observeConnectionState().test {
            // Initially no plugin -> DISCONNECTED
            assertEquals(ConnectionState.DISCONNECTED, awaitItem())

            // Set plugin -> follow its state
            pumpPluginFlow.value = plugin
            assertEquals(ConnectionState.DISCONNECTED, awaitItem())

            connectionFlow.value = ConnectionState.CONNECTED
            assertEquals(ConnectionState.CONNECTED, awaitItem())
        }
    }
}
