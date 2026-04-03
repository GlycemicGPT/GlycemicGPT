package com.glycemicgpt.mobile.plugin

import app.cash.turbine.test
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.plugin.events.PluginEvent
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.Instant

class PluginEventBusImplTest {

    private val eventBus = PluginEventBusImpl()

    @Test
    fun `publish emits event to subscribers`() = runTest {
        val event = PluginEvent.NewGlucoseReading(
            pluginId = "test.plugin",
            reading = CgmReading(
                glucoseMgDl = 120,
                trendArrow = CgmTrend.FLAT,
                timestamp = Instant.now(),
            ),
        )

        eventBus.events.test {
            eventBus.publish(event)
            assertEquals(event, awaitItem())
        }
    }

    @Test
    fun `subscribe filters by event type`() = runTest {
        val glucoseEvent = PluginEvent.NewGlucoseReading(
            pluginId = "test.plugin",
            reading = CgmReading(
                glucoseMgDl = 120,
                trendArrow = CgmTrend.FLAT,
                timestamp = Instant.now(),
            ),
        )
        val connectedEvent = PluginEvent.DeviceConnected(pluginId = "test.plugin")

        eventBus.subscribe(PluginEvent.DeviceConnected::class).test {
            eventBus.publish(glucoseEvent)
            eventBus.publish(connectedEvent)
            assertEquals(connectedEvent, awaitItem())
        }
    }

    @Test
    fun `publish blocks platform-only events from plugins`() = runTest {
        val platformEvent = PluginEvent.SafetyLimitsChanged(
            pluginId = "malicious.plugin",
            limits = SafetyLimits(),
        )

        eventBus.events.test {
            eventBus.publish(platformEvent)
            // No event should be emitted since SafetyLimitsChanged is platform-only
            expectNoEvents()
        }
    }

    @Test
    fun `publishPlatform allows platform-only events`() = runTest {
        val platformEvent = PluginEvent.SafetyLimitsChanged(
            pluginId = "platform",
            limits = SafetyLimits(),
        )

        eventBus.events.test {
            eventBus.publishPlatform(platformEvent)
            assertEquals(platformEvent, awaitItem())
        }
    }
}
