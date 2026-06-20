package com.glycemicgpt.mobile.presentation.meal

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.glycemicgpt.mobile.data.meal.CarbConfidence
import com.glycemicgpt.mobile.data.meal.CarbRange
import com.glycemicgpt.mobile.data.meal.MealDispersion
import com.glycemicgpt.mobile.presentation.theme.GlycemicGptTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Story 50.H1: the multi-sample dispersion actually renders on the estimate card.
 *
 * The card merges its descendants' semantics for screen readers, so tagged
 * children are queried on the *unmerged* tree.
 */
@RunWith(AndroidJUnit4::class)
class CarbEstimateContentUiTest {

    @get:Rule
    val compose = createComposeRule()

    private fun render(dispersion: MealDispersion?) {
        compose.setContent {
            GlycemicGptTheme {
                CarbEstimateContent(
                    range = CarbRange(40.0, 100.0),
                    confidence = CarbConfidence.LOW,
                    dispersion = dispersion,
                )
            }
        }
    }

    @Test
    fun wideSpread_rendersVisceralCautionNote() {
        val note = "Repeated looks at this photo disagreed a lot (about 40 g to " +
            "100 g) -- treat this as a rough guess, not a measurement."
        render(MealDispersion(note = note, wideSpread = true, identityAgreement = true))

        compose.onNodeWithTag("meal_dispersion_note", useUnmergedTree = true)
            .assertIsDisplayed()
        // A wide spread gets the emphasized caution treatment.
        compose.onNodeWithTag("meal_wide_spread", useUnmergedTree = true)
            .assertIsDisplayed()
        compose.onNodeWithText(note, substring = true, useUnmergedTree = true)
            .assertIsDisplayed()
        // The carb range + confidence are still shown alongside it.
        compose.onNodeWithTag("meal_carb_range", useUnmergedTree = true)
            .assertIsDisplayed()
        compose.onNodeWithTag("meal_confidence", useUnmergedTree = true)
            .assertIsDisplayed()
    }

    @Test
    fun identityDisagreement_isFlaggedDistinctly() {
        render(
            MealDispersion(
                note = "The AI didn't consistently agree on what this food is -- " +
                    "confirm the food before relying on it.",
                wideSpread = true,
                identityAgreement = false,
            )
        )
        compose.onNodeWithTag("meal_identity_disagreement", useUnmergedTree = true)
            .assertIsDisplayed()
        compose.onAllNodesWithTag("meal_wide_spread", useUnmergedTree = true)
            .assertCountEquals(0)
    }

    @Test
    fun tightAgreement_isAQuietLine_notACautionStrip() {
        render(
            MealDispersion(
                note = "Estimated from 3 reads of the photo.",
                wideSpread = false,
                identityAgreement = true,
            )
        )
        compose.onNodeWithTag("meal_dispersion_note", useUnmergedTree = true)
            .assertIsDisplayed()
        // The quiet form carries no caution flag.
        compose.onAllNodesWithTag("meal_wide_spread", useUnmergedTree = true)
            .assertCountEquals(0)
        compose.onAllNodesWithTag("meal_identity_disagreement", useUnmergedTree = true)
            .assertCountEquals(0)
    }

    @Test
    fun noDispersion_rendersNoNote() {
        render(null)
        compose.onAllNodesWithTag("meal_dispersion_note", useUnmergedTree = true)
            .assertCountEquals(0)
    }

    @Test
    fun blankNote_rendersNoNote() {
        render(MealDispersion(note = null, wideSpread = true, identityAgreement = false))
        compose.onAllNodesWithTag("meal_dispersion_note", useUnmergedTree = true)
            .assertCountEquals(0)
    }
}
