package com.glycemicgpt.weardevice.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class WatchDataRepositoryTest {

    @Before
    fun resetState() {
        WatchDataRepository.updateIoB(iob = 0f, timestampMs = 0L)
        WatchDataRepository.updateCgm(
            mgDl = 0, trend = "UNKNOWN", timestampMs = 0L,
            low = 70, high = 180, urgentLow = 55, urgentHigh = 250,
        )
        WatchDataRepository.updateAlert(type = "none", bgValue = 0, timestampMs = 0L, message = "")
        WatchDataRepository.updateWatchFaceConfig(
            showIoB = true, showGraph = true, showAlert = true,
            showSeconds = false, graphRangeHours = 3, theme = "dark",
        )
        WatchDataRepository.clearChat()
    }

    @Test
    fun `updateIoB sets correct values`() {
        WatchDataRepository.updateIoB(iob = 2.45f, timestampMs = 1000L)

        val state = WatchDataRepository.iob.value
        assertEquals(2.45f, state!!.iob, 0.001f)
        assertEquals(1000L, state.timestampMs)
    }

    @Test
    fun `updateIoB overwrites previous values`() {
        WatchDataRepository.updateIoB(iob = 1.0f, timestampMs = 100L)
        WatchDataRepository.updateIoB(iob = 3.5f, timestampMs = 200L)

        val state = WatchDataRepository.iob.value
        assertEquals(3.5f, state!!.iob, 0.001f)
        assertEquals(200L, state.timestampMs)
    }

    @Test
    fun `updateCgm sets correct values`() {
        WatchDataRepository.updateCgm(
            mgDl = 120,
            trend = "FLAT",
            timestampMs = 5000L,
            low = 70,
            high = 180,
            urgentLow = 55,
            urgentHigh = 250,
        )

        val state = WatchDataRepository.cgm.value
        assertEquals(120, state!!.mgDl)
        assertEquals("FLAT", state.trend)
        assertEquals(5000L, state.timestampMs)
        assertEquals(70, state.low)
        assertEquals(180, state.high)
        assertEquals(55, state.urgentLow)
        assertEquals(250, state.urgentHigh)
    }

    @Test
    fun `updateCgm overwrites previous values`() {
        WatchDataRepository.updateCgm(
            mgDl = 80, trend = "SINGLE_DOWN", timestampMs = 100L,
            low = 70, high = 180, urgentLow = 55, urgentHigh = 250,
        )
        WatchDataRepository.updateCgm(
            mgDl = 200, trend = "SINGLE_UP", timestampMs = 200L,
            low = 70, high = 180, urgentLow = 55, urgentHigh = 250,
        )

        val state = WatchDataRepository.cgm.value
        assertEquals(200, state!!.mgDl)
        assertEquals("SINGLE_UP", state.trend)
        assertEquals(200L, state.timestampMs)
    }

    @Test
    fun `alert initial state is null`() {
        WatchDataRepository.updateAlert(type = "none", bgValue = 0, timestampMs = 0L, message = "")
        assertNull(WatchDataRepository.alert.value)
    }

    @Test
    fun `updateAlert sets correct values`() {
        WatchDataRepository.updateAlert(
            type = "urgent_low",
            bgValue = 45,
            timestampMs = 3000L,
            message = "URGENT LOW 45 mg/dL",
        )

        val state = WatchDataRepository.alert.value
        assertEquals("urgent_low", state!!.type)
        assertEquals(45, state.bgValue)
        assertEquals(3000L, state.timestampMs)
        assertEquals("URGENT LOW 45 mg/dL", state.message)
    }

    @Test
    fun `updateAlert with none type clears alert`() {
        WatchDataRepository.updateAlert(
            type = "high",
            bgValue = 200,
            timestampMs = 1000L,
            message = "HIGH 200 mg/dL",
        )
        assertNotNull(WatchDataRepository.alert.value)

        WatchDataRepository.updateAlert(type = "none", bgValue = 0, timestampMs = 2000L, message = "")
        assertNull(WatchDataRepository.alert.value)
    }

    @Test
    fun `updateAlert overwrites previous alert`() {
        WatchDataRepository.updateAlert(
            type = "low", bgValue = 65, timestampMs = 100L, message = "LOW 65 mg/dL",
        )
        WatchDataRepository.updateAlert(
            type = "urgent_low", bgValue = 50, timestampMs = 200L, message = "URGENT LOW 50 mg/dL",
        )

        val state = WatchDataRepository.alert.value
        assertEquals("urgent_low", state!!.type)
        assertEquals(50, state.bgValue)
    }

    @Test
    fun `resetState sets expected watchFaceConfig`() {
        val config = WatchDataRepository.watchFaceConfig.value
        assertTrue(config.showIoB)
        assertTrue(config.showGraph)
        assertTrue(config.showAlert)
        assertFalse(config.showSeconds)
        assertEquals(3, config.graphRangeHours)
        assertEquals("dark", config.theme)
    }

    @Test
    fun `updateWatchFaceConfig sets correct values`() {
        WatchDataRepository.updateWatchFaceConfig(
            showIoB = false,
            showGraph = false,
            showAlert = false,
            showSeconds = true,
            graphRangeHours = 6,
            theme = "clinical_blue",
        )

        val config = WatchDataRepository.watchFaceConfig.value
        assertFalse(config.showIoB)
        assertFalse(config.showGraph)
        assertFalse(config.showAlert)
        assertTrue(config.showSeconds)
        assertEquals(6, config.graphRangeHours)
        assertEquals("clinical_blue", config.theme)
    }

    @Test
    fun `updateWatchFaceConfig overwrites previous config`() {
        WatchDataRepository.updateWatchFaceConfig(
            showIoB = false, showGraph = false, showAlert = false,
            showSeconds = true, graphRangeHours = 1, theme = "high_contrast",
        )
        WatchDataRepository.updateWatchFaceConfig(
            showIoB = true, showGraph = true, showAlert = true,
            showSeconds = false, graphRangeHours = 6, theme = "dark",
        )

        val config = WatchDataRepository.watchFaceConfig.value
        assertTrue(config.showIoB)
        assertTrue(config.showGraph)
        assertEquals(6, config.graphRangeHours)
        assertEquals("dark", config.theme)
    }

    @Test
    fun `updateWatchFaceConfig clamps invalid graphRangeHours to default`() {
        WatchDataRepository.updateWatchFaceConfig(
            showIoB = true, showGraph = true, showAlert = true,
            showSeconds = false, graphRangeHours = 99, theme = "dark",
        )
        assertEquals(3, WatchDataRepository.watchFaceConfig.value.graphRangeHours)
    }

    // --- clearAlert tests ---

    @Test
    fun `clearAlert clears active alert`() {
        WatchDataRepository.updateAlert(
            type = "high", bgValue = 200, timestampMs = 1000L, message = "HIGH",
        )
        assertNotNull(WatchDataRepository.alert.value)

        WatchDataRepository.clearAlert()
        assertNull(WatchDataRepository.alert.value)
    }

    // --- Chat state tests ---

    @Test
    fun `setChatResponse transitions to Success state`() {
        WatchDataRepository.setChatLoading()
        WatchDataRepository.setChatResponse("Your BG is stable", "Not medical advice")

        val state = WatchDataRepository.chatState.value
        assertTrue(state is WatchDataRepository.ChatState.Success)
        val success = state as WatchDataRepository.ChatState.Success
        assertEquals("Your BG is stable", success.response)
        assertEquals("Not medical advice", success.disclaimer)
    }

    @Test
    fun `setChatLoading transitions to Loading state`() {
        WatchDataRepository.setChatResponse("old response", "disclaimer")

        WatchDataRepository.setChatLoading()
        val state = WatchDataRepository.chatState.value
        assertTrue(state is WatchDataRepository.ChatState.Loading)
    }

    @Test
    fun `setChatError transitions to Error state`() {
        WatchDataRepository.setChatLoading()

        WatchDataRepository.setChatError("Phone not connected")
        val state = WatchDataRepository.chatState.value
        assertTrue(state is WatchDataRepository.ChatState.Error)
        assertEquals("Phone not connected", (state as WatchDataRepository.ChatState.Error).message)
    }

    @Test
    fun `clearChat resets to Idle state`() {
        WatchDataRepository.setChatResponse("response", "disc")
        WatchDataRepository.clearChat()

        val state = WatchDataRepository.chatState.value
        assertTrue(state is WatchDataRepository.ChatState.Idle)
    }

    @Test
    fun `updateWatchFaceConfig falls back to dark for unknown theme`() {
        WatchDataRepository.updateWatchFaceConfig(
            showIoB = true, showGraph = true, showAlert = true,
            showSeconds = false, graphRangeHours = 3, theme = "neon_green",
        )
        assertEquals("dark", WatchDataRepository.watchFaceConfig.value.theme)
    }
}
