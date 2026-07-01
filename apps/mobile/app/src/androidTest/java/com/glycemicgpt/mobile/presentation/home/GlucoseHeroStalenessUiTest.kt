package com.glycemicgpt.mobile.presentation.home

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.presentation.theme.GlycemicGptTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.time.Instant

/**
 * On-device rendering of the glucose hero staleness treatment. Uses the real
 * FreshnessPolicy.CGM bounds (STALE at 6 min, TOO_STALE at 15 min) with timestamps aged past those
 * bounds so classification is deterministic regardless of wall-clock jitter.
 */
@RunWith(AndroidJUnit4::class)
class GlucoseHeroStalenessUiTest {

    @get:Rule
    val compose = createComposeRule()

    private fun reading(ageSeconds: Long) = CgmReading(
        glucoseMgDl = 120,
        trendArrow = CgmTrend.FLAT,
        timestamp = Instant.now().minusSeconds(ageSeconds),
    )

    private fun setHero(cgm: CgmReading) {
        compose.setContent {
            GlycemicGptTheme {
                GlucoseHero(cgm = cgm, iob = null, basalRate = null, battery = null, reservoir = null)
            }
        }
    }

    @Test
    fun freshReading_showsValue_withNoStalenessBadge() {
        setHero(reading(ageSeconds = 30))

        compose.onNodeWithTag("glucose_hero_value").assertTextEquals("120")
        compose.onAllNodesWithTag("staleness_badge").assertCountEquals(0)
    }

    @Test
    fun staleReading_showsStalenessBadge_andStillShowsValue() {
        // 7 minutes: past the 6-min STALE bound, below the 15-min TOO_STALE bound.
        setHero(reading(ageSeconds = 7 * 60))

        compose.onNodeWithTag("glucose_hero_value").assertTextEquals("120")
        compose.onNodeWithTag("staleness_badge").assertExists()
        compose.onNodeWithText("Stale").assertIsDisplayed()
    }

    @Test
    fun tooStaleReading_isLabelledTooOld_butValueStillRenders() {
        // 20 minutes: past the 15-min TOO_STALE bound → de-emphasised, never hidden.
        setHero(reading(ageSeconds = 20 * 60))

        compose.onNodeWithTag("glucose_hero_value").assertTextEquals("120")
        compose.onNodeWithTag("staleness_badge").assertExists()
        compose.onNodeWithText("Too old").assertIsDisplayed()
    }
}
