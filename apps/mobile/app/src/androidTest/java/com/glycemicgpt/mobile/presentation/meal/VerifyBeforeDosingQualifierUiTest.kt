package com.glycemicgpt.mobile.presentation.meal

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.glycemicgpt.mobile.presentation.theme.GlycemicGptTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Story 50.S: the safety qualifier actually renders on screen under the tag that
 * every estimate surface (result, history, common-foods, edit dialog, home card)
 * relies on, and its visible text names the prohibited action -- not merely that
 * the [VERIFY_BEFORE_DOSING_TEXT] string constant is correct (that is the unit
 * test). This guards the "every surface shows the words, never just a number"
 * charter rule against a regression that drops or mis-tags the strip.
 */
@RunWith(AndroidJUnit4::class)
class VerifyBeforeDosingQualifierUiTest {

    @get:Rule
    val compose = createComposeRule()

    @Test
    fun qualifier_rendersTaggedAndNamesTheProhibition() {
        compose.setContent {
            GlycemicGptTheme {
                VerifyBeforeDosingQualifier()
            }
        }

        compose.onNodeWithTag(TAG_SAFETY_QUALIFIER).assertIsDisplayed()
        // The strengthened wording must be visible, not just present as a constant.
        compose.onNodeWithText("insulin dose or bolus", substring = true)
            .assertIsDisplayed()
    }
}
