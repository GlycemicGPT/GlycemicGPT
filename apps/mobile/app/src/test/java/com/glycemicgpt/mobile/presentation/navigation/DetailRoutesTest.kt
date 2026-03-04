package com.glycemicgpt.mobile.presentation.navigation

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Test

class DetailRoutesTest {

    // Note: bottomNavItems is private in NavHost.kt. This list mirrors it for assertions.
    // If bottomNavItems changes, update this list accordingly.
    private val bottomNavRoutes = listOf(
        Screen.Home.route,
        Screen.AiChat.route,
        Screen.Alerts.route,
        Screen.Settings.route,
    )

    private val detailRoutes = listOf(
        Screen.ChartDetail.route,
        Screen.TirDetail.route,
        Screen.InsulinDetail.route,
        Screen.AlertHistory.route,
    )

    // -- Route strings -----------------------------------------------------------

    @Test
    fun `ChartDetail has correct route`() {
        assertEquals("chart_detail", Screen.ChartDetail.route)
    }

    @Test
    fun `TirDetail has correct route`() {
        assertEquals("tir_detail", Screen.TirDetail.route)
    }

    @Test
    fun `InsulinDetail has correct route`() {
        assertEquals("insulin_detail", Screen.InsulinDetail.route)
    }

    @Test
    fun `AlertHistory has correct route`() {
        assertEquals("alert_history", Screen.AlertHistory.route)
    }

    // -- Not in bottom nav -------------------------------------------------------

    @Test
    fun `detail routes are not in bottom nav items`() {
        detailRoutes.forEach { route ->
            assertFalse(
                "Detail route '$route' should not be in bottom nav",
                bottomNavRoutes.contains(route),
            )
        }
    }

    // -- Uniqueness --------------------------------------------------------------

    @Test
    fun `all detail routes are unique`() {
        assertEquals(
            "Detail routes should be unique",
            detailRoutes.size,
            detailRoutes.toSet().size,
        )
    }

    @Test
    fun `detail routes do not collide with existing routes`() {
        val existingRoutes = listOf(
            Screen.Home.route,
            Screen.AiChat.route,
            Screen.Alerts.route,
            Screen.Settings.route,
            Screen.Pairing.route,
            Screen.BleDebug.route,
            Screen.Onboarding.route,
            Screen.PluginDetail.route,
        )
        detailRoutes.forEach { detailRoute ->
            existingRoutes.forEach { existing ->
                assertNotEquals(
                    "Detail route '$detailRoute' collides with '$existing'",
                    existing,
                    detailRoute,
                )
            }
        }
    }

    // -- Labels ------------------------------------------------------------------

    @Test
    fun `detail screen labels are set`() {
        assertEquals("Chart", Screen.ChartDetail.label)
        assertEquals("Time in Range", Screen.TirDetail.label)
        assertEquals("Insulin", Screen.InsulinDetail.label)
        assertEquals("Alert History", Screen.AlertHistory.label)
    }
}
