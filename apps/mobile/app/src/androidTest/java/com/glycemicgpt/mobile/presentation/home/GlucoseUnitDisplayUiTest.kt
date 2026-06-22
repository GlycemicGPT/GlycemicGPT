package com.glycemicgpt.mobile.presentation.home

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmStats
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.model.GlucoseUnit
import com.glycemicgpt.mobile.domain.model.TimeInRangeData
import com.glycemicgpt.mobile.presentation.theme.GlycemicGptTheme
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
}
