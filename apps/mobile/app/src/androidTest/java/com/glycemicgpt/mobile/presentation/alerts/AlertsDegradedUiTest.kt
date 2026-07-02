package com.glycemicgpt.mobile.presentation.alerts

import androidx.compose.material3.SnackbarHostState
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.glycemicgpt.mobile.data.local.entity.AlertEntity
import com.glycemicgpt.mobile.domain.model.GlucoseUnit
import com.glycemicgpt.mobile.presentation.theme.GlycemicGptTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * On-device rendering of the alerts surface in the degraded (backend unreachable / SSE down)
 * state: the honest banner shows, cached alerts stay visible, and no indeterminate spinner
 * remains (the AC1 no-hang assertion at the composable level).
 */
@RunWith(AndroidJUnit4::class)
class AlertsDegradedUiTest {

    @get:Rule
    val compose = createComposeRule()

    private val indeterminateSpinner = SemanticsMatcher.expectValue(
        SemanticsProperties.ProgressBarRangeInfo,
        ProgressBarRangeInfo.Indeterminate,
    )

    private fun cachedAlert(id: String = "alert-1") = AlertEntity(
        serverId = id,
        alertType = "high_warning",
        severity = "warning",
        message = "High glucose warning",
        currentValue = 250.0,
        timestampMs = System.currentTimeMillis(),
        acknowledged = false,
    )

    private fun setContent(
        degraded: Boolean,
        alerts: List<AlertEntity>,
        isLoading: Boolean = false,
    ) {
        compose.setContent {
            GlycemicGptTheme {
                AlertsContent(
                    uiState = AlertsUiState(isLoading = isLoading),
                    alerts = alerts,
                    glucoseUnit = GlucoseUnit.MGDL,
                    alertingDegraded = degraded,
                    snackbarHostState = SnackbarHostState(),
                    onRefresh = {},
                    onAcknowledge = {},
                )
            }
        }
    }

    @Test
    fun degraded_showsBanner_andKeepsCachedAlerts_withNoSpinner() {
        setContent(degraded = true, alerts = listOf(cachedAlert()))

        compose.onNodeWithTag(TAG_ALERTING_DEGRADED_BANNER).assertIsDisplayed()
        compose.onNodeWithText("High glucose warning").assertIsDisplayed()
        compose.onAllNodes(indeterminateSpinner).assertCountEquals(0)
    }

    @Test
    fun degraded_bannerIsHonest_serverAlertsPaused_noDeviceFloorClaim() {
        setContent(degraded = true, alerts = emptyList())

        // Says plainly that server-pushed alerts are paused...
        compose.onNodeWithText("Server alerts paused", substring = true).assertIsDisplayed()
        // ...and never implies a device/local alert floor is protecting the user (that's 57.9).
        compose.onNodeWithText("device", substring = true, ignoreCase = true).assertDoesNotExist()
        compose.onNodeWithText("threshold", substring = true, ignoreCase = true).assertDoesNotExist()
    }

    @Test
    fun goldenPath_rendersNoBanner() {
        setContent(degraded = false, alerts = listOf(cachedAlert()))

        compose.onAllNodesWithTag(TAG_ALERTING_DEGRADED_BANNER).assertCountEquals(0)
        compose.onNodeWithText("High glucose warning").assertIsDisplayed()
    }

    @Test
    fun degraded_withNoCachedAlerts_showsEmptyState_notBlank() {
        setContent(degraded = true, alerts = emptyList())

        compose.onNodeWithTag(TAG_ALERTING_DEGRADED_BANNER).assertIsDisplayed()
        compose.onNodeWithText("No alerts").assertIsDisplayed()
        compose.onAllNodes(indeterminateSpinner).assertCountEquals(0)
    }
}
