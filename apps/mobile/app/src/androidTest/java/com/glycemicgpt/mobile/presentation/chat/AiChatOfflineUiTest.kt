package com.glycemicgpt.mobile.presentation.chat

import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
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
 * On-device rendering of the chat offline state (AC3): a clear "can't connect" message with a
 * Retry — never an indeterminate spinner.
 */
@RunWith(AndroidJUnit4::class)
class AiChatOfflineUiTest {

    @get:Rule
    val compose = createComposeRule()

    private val indeterminateSpinner = SemanticsMatcher.expectValue(
        SemanticsProperties.ProgressBarRangeInfo,
        ProgressBarRangeInfo.Indeterminate,
    )

    @Test
    fun offlineState_showsClearMessageWithRetry_andNoSpinner() {
        compose.setContent {
            GlycemicGptTheme {
                OfflineContent(onRetry = {})
            }
        }

        compose.onNodeWithTag("ai_chat_offline").assertIsDisplayed()
        compose.onNodeWithText("Unable to Connect").assertIsDisplayed()
        compose.onNodeWithText("Retry").assertIsDisplayed()
        compose.onAllNodes(indeterminateSpinner).assertCountEquals(0)
    }

    @Test
    fun offlineState_retryInvokesCallback() {
        var retried = false
        compose.setContent {
            GlycemicGptTheme {
                OfflineContent(onRetry = { retried = true })
            }
        }

        compose.onNodeWithText("Retry").performClick()

        assertTrue(retried)
    }
}
