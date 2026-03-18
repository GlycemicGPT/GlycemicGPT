package com.glycemicgpt.weardevice.complications

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WatchGraphRendererTest {

    @Test
    fun `IMG dimensions are 400x100`() {
        assertEquals(400, WatchGraphRenderer.IMG_WIDTH)
        assertEquals(100, WatchGraphRenderer.IMG_HEIGHT)
    }

    @Test
    fun `GraphConfig defaults enable all overlays`() {
        val config = WatchGraphRenderer.GraphConfig()
        assertTrue(config.showBasalOverlay)
        assertTrue(config.showBolusMarkers)
        assertTrue(config.showIoBOverlay)
        assertTrue(config.showModeBands)
    }

    @Test
    fun `GraphConfig can disable all overlays`() {
        val config = WatchGraphRenderer.GraphConfig(
            showBasalOverlay = false,
            showBolusMarkers = false,
            showIoBOverlay = false,
            showModeBands = false,
        )
        assertEquals(false, config.showBasalOverlay)
        assertEquals(false, config.showBolusMarkers)
        assertEquals(false, config.showIoBOverlay)
        assertEquals(false, config.showModeBands)
    }
}
