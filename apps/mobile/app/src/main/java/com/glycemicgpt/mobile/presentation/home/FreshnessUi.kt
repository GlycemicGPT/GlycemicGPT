package com.glycemicgpt.mobile.presentation.home

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.glycemicgpt.mobile.domain.freshness.Freshness
import com.glycemicgpt.mobile.domain.freshness.FreshnessThresholds
import com.glycemicgpt.mobile.domain.freshness.relativeAgeLabel
import com.glycemicgpt.mobile.presentation.theme.GlucoseColors
import kotlinx.coroutines.delay
import java.time.Instant

/**
 * Reusable staleness UI for the home dashboard. One source of truth over the shared
 * [Freshness] classifier so every timestamped source (glucose + pump metrics) is aged and labelled
 * the same way — this replaces the old ad-hoc per-value colour thresholds in `GlucoseHero`.
 */

/** The current, ticking freshness of a single data point. */
data class FreshnessState(
    val freshness: Freshness,
    val ageMs: Long,
    val label: String,
)

/** Default re-evaluation cadence for the relative-age label; matches the previous FreshnessLabel. */
private const val FRESHNESS_TICK_MS = 30_000L

/** Never tick faster than this, to keep recompositions cheap. */
private const val MIN_FRESHNESS_TICK_MS = 2_000L

/**
 * Observe the live freshness of [timestamp] against [thresholds]. Recomputes on a cadence derived
 * from the thresholds so a badge appears / the age grows without needing a new reading — fast
 * enough that even the compressed debug policy crosses STALE/TOO_STALE near its documented marks,
 * but never below [MIN_FRESHNESS_TICK_MS].
 */
@Composable
fun rememberFreshness(timestamp: Instant, thresholds: FreshnessThresholds): FreshnessState {
    val tickMs = (thresholds.staleAfterMs / 4).coerceIn(MIN_FRESHNESS_TICK_MS, FRESHNESS_TICK_MS)
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(timestamp, thresholds) {
        while (true) {
            delay(tickMs)
            now = System.currentTimeMillis()
        }
    }
    val ageMs = now - timestamp.toEpochMilli()
    return FreshnessState(thresholds.classify(ageMs), ageMs, relativeAgeLabel(ageMs))
}

/** Colour for the relative-age caption: fresh green, stale amber, too-stale de-emphasised grey. */
@Composable
fun freshnessColor(freshness: Freshness): Color = when (freshness) {
    Freshness.FRESH -> GlucoseColors.InRange
    Freshness.STALE -> GlucoseColors.High
    Freshness.TOO_STALE -> MaterialTheme.colorScheme.onSurfaceVariant
}

/**
 * A compact "Stale" / "Too old" pill shown only when [freshness] is not [Freshness.FRESH]. Absent on
 * fresh data, so a fresh golden-path screen renders zero `staleness_badge` nodes.
 */
@Composable
fun StalenessBadge(freshness: Freshness, modifier: Modifier = Modifier) {
    val (text, color) = when (freshness) {
        Freshness.FRESH -> return
        Freshness.STALE -> "Stale" to GlucoseColors.High
        Freshness.TOO_STALE -> "Too old" to MaterialTheme.colorScheme.onSurfaceVariant
    }
    Text(
        text = text,
        style = MaterialTheme.typography.labelSmall,
        color = color,
        modifier = modifier
            .testTag("staleness_badge")
            .background(color.copy(alpha = 0.15f), RoundedCornerShape(4.dp))
            .padding(horizontal = 6.dp, vertical = 2.dp),
    )
}
