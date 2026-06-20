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
import com.glycemicgpt.mobile.data.meal.MealComorbidityFact
import com.glycemicgpt.mobile.data.meal.MealComorbidityNutrition
import com.glycemicgpt.mobile.data.meal.MealDispersion
import com.glycemicgpt.mobile.data.meal.MealMacro
import com.glycemicgpt.mobile.data.meal.MealNetCarbs
import com.glycemicgpt.mobile.data.meal.MealNutritionFacts
import com.glycemicgpt.mobile.presentation.theme.MealConfidenceColors
import com.glycemicgpt.mobile.presentation.theme.safetyPalette
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.util.Locale
import kotlin.math.roundToInt

/**
 * The text shown on every estimate surface. A single source of truth for the safety wording.
 * Names the prohibited action explicitly (Story 50.S); mirrors the API SAFETY_QUALIFIER constant.
 */
const val VERIFY_BEFORE_DOSING_TEXT =
    "Rough estimate — an AI guess that's often wrong. " +
        "Never use it to calculate an insulin dose or bolus."

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
    dispersion: MealDispersion? = null,
) {
    // The qualifier is announced as part of the value so it's never separable from the carbs (§12).
    // The dispersion note rides in the same merged phrase so a screen-reader hears the uncertainty
    // alongside the number, never as a detached afterthought.
    val dispersionSpeech = dispersion?.note?.let { " $it" }.orEmpty()
    val description = "${carbRangeForSpeech(range)}, ${confidenceLabel(confidence).lowercase()}. " +
        "$VERIFY_BEFORE_DOSING_TEXT.$dispersionSpeech"
    Column(
        // Merge so the carb value + confidence + qualifier are announced as one phrase, not three.
        modifier = modifier.semantics(mergeDescendants = true) { contentDescription = description },
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
        // Story 50.H1: when present (fresh estimate only), surface how much the AI's repeated reads
        // disagreed. A wide spread / identity disagreement gets a visceral caution treatment so a
        // shaky guess never reads as calm and trustworthy; a confident read stays a quiet line.
        if (dispersion != null && !dispersion.note.isNullOrBlank()) {
            MealDispersionNote(dispersion)
        }
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

/**
 * The multi-sample uncertainty note (Story 50.H1). A wide spread or an identity disagreement is
 * shown viscerally -- a caution strip the eye can't skip -- so "the AI wasn't sure" lands; a
 * tight, agreeing read is a plain quiet line. Consistency is NOT correctness, so even the quiet
 * form never reads as "safe to dose": the standing verify-before-dosing qualifier carries that.
 */
@Composable
private fun MealDispersionNote(dispersion: MealDispersion) {
    val note = dispersion.note ?: return
    val emphasize = dispersion.wideSpread || !dispersion.identityAgreement
    if (!emphasize) {
        Text(
            text = note,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.testTag("meal_dispersion_note"),
        )
        return
    }
    val palette = safetyPalette()
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("meal_dispersion_note"),
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
                text = note,
                style = MaterialTheme.typography.bodyMedium,
                color = palette.foreground,
                fontWeight = FontWeight.Medium,
                // Flag the disagreement case for tests / downstream H2 identity affordance.
                modifier = Modifier.testTag(
                    if (!dispersion.identityAgreement) "meal_identity_disagreement" else "meal_wide_spread",
                ),
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

/**
 * Glucose-framed nutrition (Story 50.N1): the assumed portion (the estimate's
 * primary sanity-check), the macros with their descriptive "how this affects
 * glucose" notes, and the caveated net-carbs figure. All copy is server-cleared
 * and rendered verbatim. Read-only -- nothing here is a dose. Caller renders this
 * only when [facts] has something to show.
 */
@Composable
fun MealNutritionContent(facts: MealNutritionFacts, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        facts.portion?.let { AssumedPortionCard(it) }
        if (facts.macros.isNotEmpty() || facts.netCarbs != null) {
            NutritionFactsCard(facts)
        }
        // Section-level never-dose note: shown whenever any nutrition surfaces
        // (including a portion-only payload with no macros/net carbs), so the
        // framing can never be dropped.
        facts.disclaimer?.takeIf { it.isNotBlank() }?.let { disclaimer ->
            Text(
                text = disclaimer,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.testTag("meal_nutrition_disclaimer"),
            )
        }
    }
}

/**
 * The assumed portion, surfaced prominently -- portion size is the dominant error
 * source in a photo estimate, so it gets its own emphasized card and an explicit
 * "does this match?" prompt.
 */
@Composable
private fun AssumedPortionCard(portion: String) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("meal_portion"),
        color = MaterialTheme.colorScheme.primaryContainer,
        shape = RoundedCornerShape(8.dp),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(
                text = "ASSUMED PORTION",
                style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
            )
            Text(
                text = portion,
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
            )
            Text(
                text = "Portion size is the biggest source of error in a photo estimate" +
                    " — does this match what you ate?",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
            )
        }
    }
}

@Composable
private fun NutritionFactsCard(facts: MealNutritionFacts) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceVariant,
        shape = RoundedCornerShape(8.dp),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                text = "Estimated nutrition",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
            )
            facts.macros.forEach { macro -> MacroRow(macro) }
            facts.netCarbs?.let { NetCarbsRow(it) }
            // The section disclaimer is rendered by MealNutritionContent (so it
            // also shows for a portion-only payload), not here.
        }
    }
}

@Composable
private fun MacroRow(macro: MealMacro) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("meal_macro"),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                text = macro.label,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = formatMacroValue(macro.value, macro.unit),
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Medium,
                color = MaterialTheme.colorScheme.onSurface,
            )
        }
        macro.glucoseNote?.let { note ->
            Text(
                text = note,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.testTag("meal_macro_note"),
            )
        }
    }
}

@Composable
private fun NetCarbsRow(netCarbs: MealNetCarbs) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("meal_net_carbs"),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                text = "Net carbs",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = formatNetCarbs(netCarbs.low, netCarbs.high),
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Medium,
                color = MaterialTheme.colorScheme.onSurface,
            )
        }
        // The net-carbs caveat rides a calm-caution strip (not error red): named
        // as inexact, pointing back to total carbs, carrying the never-dose line.
        CautionStrip(text = netCarbs.caveat, testTag = "meal_net_carbs_caveat")
    }
}

/**
 * Format a macro as "32 g" / "640 kcal" -- whole units, no false precision on an
 * estimate. Rounds to whole units (not the one-decimal carb-input style) so the
 * value reads identically to the web client for the same server data.
 */
private fun formatMacroValue(value: Double, unit: String): String =
    "${value.roundToInt()} $unit".trim()

/**
 * Render a net-carb band as "≈ 34–49 g" (or "≈ 26 g" when the rounded endpoints
 * meet). Whole grams, matching the web client's net-carb rendering.
 */
fun formatNetCarbs(low: Double, high: Double): String {
    val lo = low.roundToInt()
    val hi = high.roundToInt()
    return if (lo == hi) "≈ $lo g" else "≈ $lo–$hi g"
}

/**
 * Grounding-backed comorbidity / label nutrition: saturated fat,
 * sugars, and sodium when an authoritative source published them. GROUNDING-ONLY
 * (never from the photo) and identity-gated, so the caller renders this only for a
 * grounded record. Framed as blood-pressure / cardiovascular awareness, never a
 * directive: each figure carries its descriptive note, sugars carry the "sugar-free
 * isn't carb-free" reminder, the block is attributed to its source (distinct from
 * the vision estimate), and the never-dose disclaimer closes it. All copy is
 * server-cleared and rendered verbatim. Read-only -- nothing here is a dose.
 */
@Composable
fun MealComorbidityContent(
    comorbidity: MealComorbidityNutrition,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .testTag("meal_comorbidity"),
        color = MaterialTheme.colorScheme.surfaceVariant,
        shape = RoundedCornerShape(8.dp),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                text = "Heart & blood-pressure awareness",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
            )
            comorbidity.facts.forEach { fact -> ComorbidityRow(fact) }
            comorbidity.sugarNote?.let { note -> ComorbidityCaution(note) }
            // Attribution: these are published reference figures, distinct from the
            // photo estimate, so name the source (and its trust tier when present).
            comorbidity.source?.let { source ->
                val tier = comorbidity.trustTier?.lowercase(Locale.US)
                Text(
                    text = if (tier != null) "From $source ($tier source)" else "From $source",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.testTag("meal_comorbidity_source"),
                )
            }
            comorbidity.disclaimer?.takeIf { it.isNotBlank() }?.let { disclaimer ->
                Text(
                    text = disclaimer,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.testTag("meal_comorbidity_disclaimer"),
                )
            }
        }
    }
}

@Composable
private fun ComorbidityRow(fact: MealComorbidityFact) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("meal_comorbidity_fact"),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                text = fact.label,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = formatMacroValue(fact.value, fact.unit),
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Medium,
                color = MaterialTheme.colorScheme.onSurface,
            )
        }
        fact.note?.let { note ->
            Text(
                text = note,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.testTag("meal_comorbidity_note"),
            )
        }
    }
}

/** The "sugar-free isn't carb-free" reminder, on the shared calm-caution strip. */
@Composable
private fun ComorbidityCaution(note: String) {
    CautionStrip(text = note, testTag = "meal_comorbidity_sugar_note")
}

/**
 * A calm-caution strip (info icon + text on the safety palette, NOT error red):
 * the single source of truth for the never-dose-adjacent caveats so the net-carbs
 * caveat and the comorbidity sugar note can't drift apart visually. The caller
 * supplies the verbatim server text and the test tag for that surface.
 */
@Composable
private fun CautionStrip(text: String, testTag: String) {
    val palette = safetyPalette()
    Surface(color = palette.background, shape = RoundedCornerShape(8.dp)) {
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
                text = text,
                style = MaterialTheme.typography.bodySmall,
                color = palette.foreground,
                modifier = Modifier.testTag(testTag),
            )
        }
    }
}

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
