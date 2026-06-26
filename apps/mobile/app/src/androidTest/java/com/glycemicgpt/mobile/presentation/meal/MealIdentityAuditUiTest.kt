package com.glycemicgpt.mobile.presentation.meal

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.glycemicgpt.mobile.data.meal.AuditSample
import com.glycemicgpt.mobile.data.meal.CarbConfidence
import com.glycemicgpt.mobile.data.meal.CarbRange
import com.glycemicgpt.mobile.data.meal.FoodRecord
import com.glycemicgpt.mobile.data.meal.FoodRecordSource
import com.glycemicgpt.mobile.data.meal.MealAudit
import com.glycemicgpt.mobile.data.meal.MealDispersion
import com.glycemicgpt.mobile.presentation.theme.GlycemicGptTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Stories 50.H2 / 50.H3: the identity-confirm section and the "how was this
 * estimated" audit affordance render their states correctly on-device.
 */
@RunWith(AndroidJUnit4::class)
class MealIdentityAuditUiTest {

    @get:Rule
    val compose = createComposeRule()

    private fun record(
        confirmed: String? = null,
        identityConfirmed: Boolean = false,
        suggested: String? = null,
        identityAgreement: Boolean = true,
    ) = FoodRecord(
        id = "r",
        mealTimestamp = null,
        foodDescription = "spaghetti",
        estimate = CarbRange(40.0, 60.0),
        confidence = CarbConfidence.MEDIUM,
        source = FoodRecordSource.AI_ESTIMATE,
        correction = null,
        correctedAt = null,
        commonFoodId = null,
        createdAt = null,
        dispersion = MealDispersion(
            note = "Estimated from 3 reads of the photo.",
            wideSpread = false,
            identityAgreement = identityAgreement,
        ),
        confirmedFoodName = confirmed,
        identityConfirmed = identityConfirmed,
        suggestedIdentity = suggested,
    )

    private fun renderIdentity(record: FoodRecord, uiState: MealLogUiState = MealLogUiState()) {
        compose.setContent {
            GlycemicGptTheme {
                MealIdentitySection(
                    record = record,
                    uiState = uiState,
                    onStartEdit = {},
                    onCancelEdit = {},
                    onConfirm = {},
                )
            }
        }
    }

    @Test
    fun unconfirmed_showsConfirmAndCorrect() {
        renderIdentity(record(suggested = "my lasagna"))
        compose.onNodeWithTag("meal_identity", useUnmergedTree = true).assertIsDisplayed()
        compose.onNodeWithTag("meal_identity_confirm", useUnmergedTree = true).assertIsDisplayed()
        compose.onNodeWithTag("meal_identity_correct", useUnmergedTree = true).assertIsDisplayed()
    }

    @Test
    fun identityDisagreement_showsCautionCue() {
        renderIdentity(record(identityAgreement = false))
        compose.onNodeWithTag("meal_identity_disagreement_cue", useUnmergedTree = true)
            .assertIsDisplayed()
    }

    @Test
    fun confirmed_showsCheckmarkAndEdit_notConfirmButton() {
        renderIdentity(record(confirmed = "homemade lasagna", identityConfirmed = true))
        compose.onNodeWithTag("meal_identity_confirmed", useUnmergedTree = true)
            .assertIsDisplayed()
        compose.onNodeWithTag("meal_identity_edit", useUnmergedTree = true).assertIsDisplayed()
        compose.onAllNodesWithTag("meal_identity_confirm", useUnmergedTree = true)
            .assertCountEquals(0)
    }

    @Test
    fun editing_showsTextField() {
        renderIdentity(record(), MealLogUiState(isEditingIdentity = true))
        compose.onNodeWithTag("meal_identity_editor", useUnmergedTree = true).assertIsDisplayed()
        compose.onNodeWithTag("meal_identity_input", useUnmergedTree = true).assertIsDisplayed()
    }

    private fun renderAudit(uiState: MealLogUiState) {
        compose.setContent {
            GlycemicGptTheme {
                MealAuditSection(uiState = uiState, onLoad = {}, onHide = {})
            }
        }
    }

    @Test
    fun audit_collapsed_showsLoadButton() {
        renderAudit(MealLogUiState())
        compose.onNodeWithTag("meal_audit_button", useUnmergedTree = true).assertIsDisplayed()
        compose.onAllNodesWithTag("meal_audit_detail", useUnmergedTree = true).assertCountEquals(0)
    }

    @Test
    fun audit_loaded_showsProvenance() {
        val audit = MealAudit(
            foodRecordId = "r",
            samples = listOf(AuditSample(CarbRange(40.0, 50.0), "pasta")),
            confidence = CarbConfidence.MEDIUM,
            samplesUsed = 3,
            wideSpread = false,
            identityAgreement = true,
            grounded = true,
            groundingSource = "Your meal history",
            identityUsed = "pasta",
        )
        renderAudit(MealLogUiState(audit = audit))
        compose.onNodeWithTag("meal_audit_detail", useUnmergedTree = true).assertIsDisplayed()
        compose.onNodeWithTag("meal_audit_precedence", useUnmergedTree = true).assertIsDisplayed()
    }
}
