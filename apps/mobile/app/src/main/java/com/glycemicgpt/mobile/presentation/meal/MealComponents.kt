package com.glycemicgpt.mobile.presentation.meal

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.glycemicgpt.mobile.data.meal.CarbConfidence
import com.glycemicgpt.mobile.data.meal.CarbRange
import com.glycemicgpt.mobile.presentation.theme.MealConfidenceColors
import com.glycemicgpt.mobile.presentation.theme.safetyPalette
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.util.Locale

/** The text shown on every estimate surface. A single source of truth for the safety wording. */
const val VERIFY_BEFORE_DOSING_TEXT = "Estimate — verify before dosing"

/** testTag for the always-on safety qualifier. Present on result, history, and common-food surfaces. */
const val TAG_SAFETY_QUALIFIER = "meal_safety_qualifier"

/**
 * The NON-NEGOTIABLE safety qualifier. It must accompany every carb estimate so a user never
 * mistakes a guess about a photo for a dosing instruction. Carbs only — never insulin.
 */
@Composable
fun VerifyBeforeDosingQualifier(modifier: Modifier = Modifier) {
    // Soft-amber "calm caution" strip, never error red -- a standing note, not an alarm.
    val palette = safetyPalette()
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .testTag(TAG_SAFETY_QUALIFIER),
        color = palette.background,
        shape = RoundedCornerShape(8.dp),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = Icons.Default.Info,
                contentDescription = null,
                tint = palette.icon,
                modifier = Modifier.size(18.dp),
            )
            Spacer(modifier = Modifier.width(8.dp))
            Text(
                text = VERIFY_BEFORE_DOSING_TEXT,
                style = MaterialTheme.typography.labelLarge,
                color = palette.foreground,
                fontWeight = FontWeight.Medium,
            )
        }
    }
}

/**
 * Carb range + confidence, the way every estimate is shown. Never a lone integer: a single-point
 * estimate still renders as "≈ N g", and the confidence is always present alongside it.
 */
@Composable
fun CarbEstimateContent(
    range: CarbRange,
    confidence: CarbConfidence,
    modifier: Modifier = Modifier,
    isCorrected: Boolean = false,
    originalRange: CarbRange? = null,
) {
    // The qualifier is announced as part of the value so it's never separable from the carbs (§12).
    val description = "${carbRangeForSpeech(range)}, ${confidenceLabel(confidence).lowercase()}. " +
        "$VERIFY_BEFORE_DOSING_TEXT."
    Column(
        modifier = modifier.semantics { contentDescription = description },
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Text(
            text = formatCarbRange(range),
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.testTag("meal_carb_range"),
        )
        Text(
            text = confidenceLabel(confidence),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.testTag("meal_confidence"),
        )
        ConfidenceBar(confidence)
        if (isCorrected && originalRange != null) {
            Text(
                text = "You corrected this. AI estimated ${formatCarbRange(originalRange)}.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.testTag("meal_corrected_note"),
            )
        }
    }
}

/** Confidence shown as a short colored bar (color + length, never color alone). Hidden when unknown. */
@Composable
private fun ConfidenceBar(confidence: CarbConfidence) {
    val (fraction, color) = when (confidence) {
        CarbConfidence.HIGH -> 1f to MealConfidenceColors.High
        CarbConfidence.MEDIUM -> 0.6f to MealConfidenceColors.Medium
        CarbConfidence.LOW -> 0.3f to MealConfidenceColors.Low
        CarbConfidence.UNKNOWN -> return
    }
    Box(
        modifier = Modifier
            .width(120.dp)
            .height(6.dp)
            .clip(RoundedCornerShape(3.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .testTag("meal_confidence_bar"),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth(fraction)
                .fillMaxHeight()
                .clip(RoundedCornerShape(3.dp))
                .background(color),
        )
    }
}

private val timestampFormatter: DateTimeFormatter =
    DateTimeFormatter.ofLocalizedDateTime(FormatStyle.MEDIUM).withZone(ZoneId.systemDefault())

fun formatMealTimestamp(instant: Instant?): String =
    instant?.let { timestampFormatter.format(it) } ?: "Unknown time"

/** Render a carb range as "≈ 40–55 g" (or "≈ 50 g" when low == high). Carbs only — no dose. */
fun formatCarbRange(range: CarbRange): String {
    val low = formatGrams(range.lowGrams)
    val high = formatGrams(range.highGrams)
    return if (low == high) "≈ $low g carbs" else "≈ $low–$high g carbs"
}

private fun formatGrams(value: Double): String =
    if (value % 1.0 == 0.0) value.toInt().toString() else String.format(Locale.US, "%.1f", value)

/** Spoken form of a carb range for screen readers (avoids reading "≈" / "–" literally). */
private fun carbRangeForSpeech(range: CarbRange): String {
    val low = formatGrams(range.lowGrams)
    val high = formatGrams(range.highGrams)
    return if (low == high) {
        "Estimated $low grams of carbs"
    } else {
        "Estimated $low to $high grams of carbs"
    }
}

fun confidenceLabel(confidence: CarbConfidence): String = when (confidence) {
    CarbConfidence.LOW -> "Low confidence"
    CarbConfidence.MEDIUM -> "Medium confidence"
    CarbConfidence.HIGH -> "High confidence"
    CarbConfidence.UNKNOWN -> "Confidence unavailable"
}

/**
 * Editable grams string for correction/edit text fields. Reuses the display rounding so a
 * prefilled field never shows more precision than the value rendered elsewhere.
 */
internal fun formatEditableGrams(value: Double): String = formatGrams(value)

/** Full-screen centered spinner with an optional caption, shared across the meal screens. */
@Composable
fun MealCenteredSpinner(message: String? = null, modifier: Modifier = Modifier) {
    Box(modifier = modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            CircularProgressIndicator(color = MaterialTheme.colorScheme.primary)
            if (message != null) {
                Spacer(Modifier.height(12.dp))
                Text(
                    text = message,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/** Full-screen centered message (empty/disabled states), shared across the meal screens. */
@Composable
fun MealCenteredMessage(message: String, modifier: Modifier = Modifier) {
    Box(modifier = modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(
            text = message,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(32.dp),
        )
    }
}
