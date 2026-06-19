package com.glycemicgpt.mobile.presentation.meal

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.glycemicgpt.mobile.data.meal.MealMacro
import com.glycemicgpt.mobile.data.meal.MealNetCarbs
import com.glycemicgpt.mobile.data.meal.MealNutritionFacts
import com.glycemicgpt.mobile.presentation.theme.GlycemicGptTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Story 50.N1: the glucose-framed nutrition actually renders on screen -- the
 * assumed portion (prominent sanity-check), the macros with their descriptive
 * "later" framing (no timing number), and the net-carbs figure behind its
 * ADA/never-dose caveat. Guards against a regression that drops or mis-tags any
 * of these, and against dosing language ever creeping into the surfaced copy.
 */
@RunWith(AndroidJUnit4::class)
class MealNutritionContentUiTest {

    @get:Rule
    val compose = createComposeRule()

    private val facts = MealNutritionFacts(
        portion = "One large takeout bowl, about 1.5 cups of rice",
        macros = listOf(
            MealMacro(
                key = "protein_grams",
                label = "Protein",
                value = 32.0,
                unit = "g",
                glucoseNote = "Protein can nudge glucose up later, in the hours after a meal.",
            ),
            MealMacro(
                key = "fiber_grams",
                label = "Fiber",
                value = 9.0,
                unit = "g",
                glucoseNote = "Fiber slows and blunts the rise in glucose.",
            ),
        ),
        netCarbs = MealNetCarbs(
            low = 31.0,
            high = 46.0,
            caveat = "Net carbs (total carbs minus fiber) is a rough estimate, not exact — " +
                "the ADA recommends counting total carbs. AI estimate, often wrong — " +
                "never use it to dose or bolus.",
        ),
        disclaimer = "These nutrition figures are rough AI estimates that describe the meal — " +
            "never use it to dose or bolus.",
    )

    @Test
    fun portion_isSurfacedAsTheSanityCheck() {
        compose.setContent { GlycemicGptTheme { MealNutritionContent(facts) } }

        compose.onNodeWithTag("meal_portion").assertIsDisplayed()
        compose.onNodeWithText("about 1.5 cups of rice", substring = true).assertIsDisplayed()
        compose.onNodeWithText("does this match what you ate", substring = true)
            .assertIsDisplayed()
    }

    @Test
    fun macros_renderWithTheirGlucoseFraming() {
        compose.setContent { GlycemicGptTheme { MealNutritionContent(facts) } }

        compose.onNodeWithText("Protein").assertIsDisplayed()
        compose.onNodeWithText("32 g").assertIsDisplayed()
        compose.onNodeWithText("nudge glucose up later", substring = true).assertIsDisplayed()
        compose.onNodeWithText("blunts the rise", substring = true).assertIsDisplayed()
    }

    @Test
    fun netCarbs_areShownOnlyBehindTheCaveat() {
        compose.setContent { GlycemicGptTheme { MealNutritionContent(facts) } }

        compose.onNodeWithTag("meal_net_carbs").assertIsDisplayed()
        compose.onNodeWithText("≈ 31–46 g", substring = true).assertIsDisplayed()
        // "ADA recommends counting total carbs" is unique to the net-carbs caveat.
        compose.onNodeWithTag("meal_net_carbs_caveat")
            .assertTextContains("ADA recommends counting total carbs", substring = true)
        // The never-dose prohibition rides BOTH the net-carbs caveat and the
        // section disclaimer (a deliberate belt-and-braces), so two nodes carry
        // it -- assert exactly that rather than expecting a single node.
        compose.onAllNodesWithText("never use it to dose or bolus", substring = true)
            .assertCountEquals(2)
    }

    @Test
    fun disclaimer_carriesTheNeverDoseFraming() {
        compose.setContent { GlycemicGptTheme { MealNutritionContent(facts) } }

        compose.onNodeWithTag("meal_nutrition_disclaimer").assertIsDisplayed()
    }
}
