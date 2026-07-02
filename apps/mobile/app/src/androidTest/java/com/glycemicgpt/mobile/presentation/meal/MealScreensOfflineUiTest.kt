package com.glycemicgpt.mobile.presentation.meal

import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.glycemicgpt.mobile.presentation.theme.GlycemicGptTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * On-device rendering of the backend-only meal screens in the offline/failed state (AC3): a clear
 * message + Retry — never an indeterminate spinner, never a misleading "nothing logged yet" empty
 * state while the backend is unreachable.
 */
@RunWith(AndroidJUnit4::class)
class MealScreensOfflineUiTest {

    @get:Rule
    val compose = createComposeRule()

    private val indeterminateSpinner = SemanticsMatcher.expectValue(
        SemanticsProperties.ProgressBarRangeInfo,
        ProgressBarRangeInfo.Indeterminate,
    )

    // -- Meal history -----------------------------------------------------------

    @Test
    fun mealHistory_offline_showsErrorWithRetry_noSpinner_noMisleadingEmptyState() {
        val offline = MealHistoryUiState(
            isLoading = false,
            errorMessage = "Can't reach your server — your meal history isn't available right now.",
        )
        compose.setContent {
            GlycemicGptTheme {
                MealHistoryBody(uiState = offline, onRetry = {}, onDelete = {})
            }
        }

        compose.onNodeWithTag("meal_history_error").assertIsDisplayed()
        compose.onNodeWithTag("meal_error_retry").assertIsDisplayed()
        compose.onAllNodes(indeterminateSpinner).assertCountEquals(0)
        compose.onAllNodesWithTag("meal_history_empty").assertCountEquals(0)
    }

    @Test
    fun mealHistory_retryInvokesCallback() {
        var retried = false
        val offline = MealHistoryUiState(isLoading = false, errorMessage = "Can't reach your server.")
        compose.setContent {
            GlycemicGptTheme {
                MealHistoryBody(uiState = offline, onRetry = { retried = true }, onDelete = {})
            }
        }

        compose.onNodeWithTag("meal_error_retry").performClick()

        assertTrue(retried)
    }

    @Test
    fun mealHistory_goldenPath_rendersListWithoutErrorState() {
        val loaded = MealHistoryUiState(isLoading = false, records = emptyList())
        compose.setContent {
            GlycemicGptTheme {
                MealHistoryBody(uiState = loaded, onRetry = {}, onDelete = {})
            }
        }

        compose.onNodeWithTag("meal_history_empty").assertIsDisplayed()
        compose.onAllNodesWithTag("meal_history_error").assertCountEquals(0)
        compose.onAllNodes(indeterminateSpinner).assertCountEquals(0)
    }

    // -- Common foods -----------------------------------------------------------

    @Test
    fun commonFoods_offline_showsErrorWithRetry_noSpinner_noMisleadingEmptyState() {
        val offline = CommonFoodsUiState(
            isLoading = false,
            errorMessage = "Can't reach your server — your common foods aren't available right now.",
        )
        compose.setContent {
            GlycemicGptTheme {
                CommonFoodsBody(
                    uiState = offline,
                    onRetry = {},
                    onReLog = {},
                    onEdit = {},
                    onDelete = {},
                )
            }
        }

        compose.onNodeWithTag("common_foods_error").assertIsDisplayed()
        compose.onNodeWithTag("meal_error_retry").assertIsDisplayed()
        compose.onAllNodes(indeterminateSpinner).assertCountEquals(0)
        compose.onAllNodesWithTag("common_foods_empty").assertCountEquals(0)
    }

    @Test
    fun commonFoods_retryInvokesCallback() {
        var retried = false
        val offline = CommonFoodsUiState(isLoading = false, errorMessage = "Can't reach your server.")
        compose.setContent {
            GlycemicGptTheme {
                CommonFoodsBody(
                    uiState = offline,
                    onRetry = { retried = true },
                    onReLog = {},
                    onEdit = {},
                    onDelete = {},
                )
            }
        }

        compose.onNodeWithTag("meal_error_retry").performClick()

        assertTrue(retried)
    }

    @Test
    fun commonFoods_loadingState_isTheOnlyStateWithASpinner() {
        compose.setContent {
            GlycemicGptTheme {
                CommonFoodsBody(
                    uiState = CommonFoodsUiState(isLoading = true),
                    onRetry = {},
                    onReLog = {},
                    onEdit = {},
                    onDelete = {},
                )
            }
        }

        // Sanity check that the spinner matcher actually matches our spinner, so the
        // zero-spinner assertions above cannot pass vacuously.
        compose.onAllNodes(indeterminateSpinner).assertCountEquals(1)
    }

    @Test
    fun commonFoods_goldenPath_rendersEmptyStateWithoutErrorState() {
        compose.setContent {
            GlycemicGptTheme {
                CommonFoodsBody(
                    uiState = CommonFoodsUiState(isLoading = false),
                    onRetry = {},
                    onReLog = {},
                    onEdit = {},
                    onDelete = {},
                )
            }
        }

        compose.onNodeWithText("No common foods yet", substring = true).assertIsDisplayed()
        compose.onAllNodesWithTag("common_foods_error").assertCountEquals(0)
    }
}
