package com.glycemicgpt.mobile.presentation.home

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.click
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmStats
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.model.GlucoseUnit
import com.glycemicgpt.mobile.domain.model.TimeInRangeData
import com.glycemicgpt.mobile.presentation.theme.GlycemicGptTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.time.Instant

/**
 * On-device rendering of the dashboard glucose surfaces in both units. Confirms the
 * displayed number, label, and the spoken (TalkBack) accessibility string convert for
 * mmol/L users while the color/threshold logic keeps reading raw mg/dL.
 */
@RunWith(AndroidJUnit4::class)
class GlucoseUnitDisplayUiTest {

    @get:Rule
    val compose = createComposeRule()

    private val reading = CgmReading(
        glucoseMgDl = 120,
        trendArrow = CgmTrend.FLAT,
        timestamp = Instant.now(),
    )

    @Test
    fun glucoseHero_mgdl_showsRawValueAndLabel() {
        compose.setContent {
            GlycemicGptTheme {
                GlucoseHero(
                    cgm = reading,
                    iob = null,
                    basalRate = null,
                    battery = null,
                    reservoir = null,
                    glucoseUnit = GlucoseUnit.MGDL,
                )
            }
        }

        compose.onNodeWithTag("glucose_hero_value").assertTextEquals("120")
        compose.onNodeWithText("mg/dL").assertIsDisplayed()
        compose.onNodeWithContentDescription("milligrams per deciliter", substring = true)
            .assertExists()
    }

    @Test
    fun glucoseHero_mmol_convertsValueLabelAndSpokenUnit() {
        compose.setContent {
            GlycemicGptTheme {
                GlucoseHero(
                    cgm = reading,
                    iob = null,
                    basalRate = null,
                    battery = null,
                    reservoir = null,
                    glucoseUnit = GlucoseUnit.MMOL,
                )
            }
        }

        // 120 mg/dL -> 6.7 mmol/L
        compose.onNodeWithTag("glucose_hero_value").assertTextEquals("6.7")
        compose.onNodeWithText("mmol/L").assertIsDisplayed()
        compose.onNodeWithContentDescription("6.7 millimoles per liter", substring = true)
            .assertExists()
    }

    @Test
    fun timeInRangeBar_mmol_convertsTargetLabel() {
        compose.setContent {
            GlycemicGptTheme {
                TimeInRangeBar(
                    data = TimeInRangeData(
                        urgentLowPercent = 1f,
                        lowPercent = 4f,
                        inRangePercent = 80f,
                        highPercent = 10f,
                        urgentHighPercent = 5f,
                        totalReadings = 288,
                    ),
                    selectedPeriod = TirPeriod.TWENTY_FOUR_HOURS,
                    onPeriodSelected = {},
                    glucoseUnit = GlucoseUnit.MMOL,
                )
            }
        }

        // Default thresholds 70-180 mg/dL -> 3.9-10.0 mmol/L
        compose.onNodeWithTag("tir_target_range").assertTextEquals("Target: 3.9-10.0 mmol/L")
    }

    @Test
    fun cgmStatsCard_mmol_convertsMeanButKeepsGmiPercent() {
        compose.setContent {
            GlycemicGptTheme {
                CgmStatsCard(
                    stats = CgmStats(
                        meanGlucose = 120f,
                        stdDev = 36f,
                        cvPercent = 30f,
                        gmi = 6.18f,
                        readingsCount = 288,
                    ),
                    selectedPeriod = TirPeriod.TWENTY_FOUR_HOURS,
                    onPeriodSelected = {},
                    glucoseUnit = GlucoseUnit.MMOL,
                )
            }
        }

        // mean 120 -> 6.7 mmol/L; GMI stays a percentage (6.2%).
        compose.onNodeWithText("6.7 mmol/L").assertIsDisplayed()
        compose.onNodeWithText("6.2%").assertIsDisplayed()
    }

    @Test
    fun glucoseTrendChart_mmol_convertsTooltipAndKeepsMgdlPlotGeometry() {
        // The chart's Y-axis labels are drawn straight onto the Canvas (no semantics node), so the
        // tooltip -- which renders through the same GlucoseFormat path -- is the queryable proxy for
        // "this surface converts to the user's unit". Its vertical placement is derived from the
        // mg/dL geometry (CHART_Y_MIN..CHART_Y_MAX), so it also guards against a regression that
        // rescaled the plot by the display unit.
        val reading = CgmReading(
            glucoseMgDl = 180,
            trendArrow = CgmTrend.FLAT,
            timestamp = Instant.now(),
        )
        compose.setContent {
            GlycemicGptTheme {
                GlucoseTrendChart(
                    readings = listOf(reading),
                    iobReadings = emptyList(),
                    basalReadings = emptyList(),
                    bolusEvents = emptyList(),
                    selectedPeriod = ChartPeriod.THREE_HOURS,
                    onPeriodSelected = {},
                    glucoseUnit = GlucoseUnit.MMOL,
                    isDetailMode = true,
                    showPeriodSelector = false,
                    modifier = Modifier.fillMaxWidth().height(360.dp),
                )
            }
        }

        // Tap the right edge (= the most recent reading, at "now") to surface the tooltip. The
        // hit-test maps x to a timestamp, so the y coordinate is irrelevant here.
        compose.onNodeWithTag("glucose_chart").performTouchInput {
            click(Offset(width - 1f, centerY))
        }

        // (a) 180 mg/dL renders as 10.0 mmol/L with the converted label.
        compose.onNodeWithText("10.0 mmol/L").assertIsDisplayed()

        // (b) 180 sits high on the 40-300 mg/dL axis, so its tooltip lands in the upper half of the
        // chart. A bug that plotted the converted value (10.0) against the mg/dL axis would clamp to
        // the floor and push the tooltip to the bottom.
        val chart = compose.onNodeWithTag("glucose_chart").getUnclippedBoundsInRoot()
        val tooltip = compose.onNodeWithText("10.0 mmol/L").getUnclippedBoundsInRoot()
        assertTrue(
            "Tooltip for 180 mg/dL must sit in the upper half of the chart (mg/dL geometry), " +
                "not be rescaled by the display unit",
            (tooltip.top - chart.top) < (chart.bottom - chart.top) / 2,
        )
    }
}
