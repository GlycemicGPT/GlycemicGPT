package com.glycemicgpt.mobile.presentation.home

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.domain.model.TimeInRangeData
import com.glycemicgpt.mobile.presentation.theme.GlucoseColors

/**
 * Time periods for analytics cards. Entries beyond the user's local data retention
 * setting are filtered out at the UI level (see [maxRetentionDays] on card composables).
 * All entries are kept in the enum to support users who increase retention up to 30 days.
 */
enum class TirPeriod(val label: String, val hours: Long, val daysBack: Int) {
    TWENTY_FOUR_HOURS("24H", 24, 0),
    THREE_DAYS("3D", 72, 2),
    SEVEN_DAYS("7D", 168, 6),
    FOURTEEN_DAYS("14D", 336, 13),
    THIRTY_DAYS("30D", 720, 29),
}

// 5-bucket clinical color palette
private val ColorUrgentLow = GlucoseColors.UrgentLow  // Red
private val ColorLow = GlucoseColors.Low               // Yellow/Orange
private val ColorInRange = GlucoseColors.InRange        // Green
private val ColorHigh = GlucoseColors.High              // Yellow
private val ColorUrgentHigh = GlucoseColors.UrgentHigh  // Red/Orange

@Composable
fun TimeInRangeBar(
    data: TimeInRangeData?,
    selectedPeriod: TirPeriod,
    onPeriodSelected: (TirPeriod) -> Unit,
    thresholds: GlucoseThresholds = GlucoseThresholds(),
    maxRetentionDays: Int = AppSettingsStore.DEFAULT_RETENTION_DAYS,
    modifier: Modifier = Modifier,
) {
    val safeRetention = maxRetentionDays.coerceAtLeast(1)
    val availablePeriods = TirPeriod.entries.filter { it.hours / 24 <= safeRetention }
    val effectivePeriod = if (selectedPeriod in availablePeriods) selectedPeriod else availablePeriods.first()
    val a11yDescription = if (data != null && data.totalReadings > 0) {
        ("Time in range: %.0f%% urgent low, %.0f%% low, %.0f%% in range, " +
            "%.0f%% high, %.0f%% urgent high, " +
            "target %d-%d mg/dL, %d readings over %s").format(
                data.urgentLowPercent,
                data.lowPercent,
                data.inRangePercent,
                data.highPercent,
                data.urgentHighPercent,
                thresholds.low,
                thresholds.high,
                data.totalReadings,
                effectivePeriod.label,
            )
    } else {
        "Time in range: no glucose readings for this period"
    }

    Card(
        modifier = modifier
            .fillMaxWidth()
            .semantics { contentDescription = a11yDescription }
            .testTag("tir_bar"),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface,
        ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
        ) {
            // Header: title + quality label
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "Time in Range",
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                if (data != null && data.totalReadings > 0) {
                    val (qualityLabel, qualityColor) = qualityAssessment(data.inRangePercent)
                    Text(
                        text = qualityLabel,
                        style = MaterialTheme.typography.labelMedium,
                        fontWeight = FontWeight.SemiBold,
                        color = qualityColor,
                        modifier = Modifier.testTag("tir_quality_label"),
                    )
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            // Period selector chips
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
            ) {
                availablePeriods.forEach { period ->
                    FilterChip(
                        selected = period == effectivePeriod,
                        onClick = { onPeriodSelected(period) },
                        label = {
                            Text(
                                text = period.label,
                                style = MaterialTheme.typography.labelSmall,
                            )
                        },
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor = MaterialTheme.colorScheme.primary,
                            selectedLabelColor = MaterialTheme.colorScheme.onPrimary,
                        ),
                        modifier = Modifier.testTag("tir_period_chip_${period.label}"),
                    )
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            if (data == null || data.totalReadings == 0) {
                Text(
                    text = "No glucose readings for this period",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth(),
                )
            } else {
                // 5-bucket stacked horizontal bar
                FiveBucketStackedBar(
                    urgentLowPercent = data.urgentLowPercent,
                    lowPercent = data.lowPercent,
                    inRangePercent = data.inRangePercent,
                    highPercent = data.highPercent,
                    urgentHighPercent = data.urgentHighPercent,
                )

                Spacer(modifier = Modifier.height(12.dp))

                // Legend: two rows for 5 buckets
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceEvenly,
                ) {
                    LegendEntry(
                        color = ColorUrgentLow,
                        label = "<${thresholds.urgentLow}",
                        percent = data.urgentLowPercent,
                    )
                    LegendEntry(
                        color = ColorLow,
                        label = "${thresholds.urgentLow}-${thresholds.low}",
                        percent = data.lowPercent,
                    )
                    LegendEntry(
                        color = ColorInRange,
                        label = "${thresholds.low}-${thresholds.high}",
                        percent = data.inRangePercent,
                    )
                }
                Spacer(modifier = Modifier.height(4.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceEvenly,
                ) {
                    LegendEntry(
                        color = ColorHigh,
                        label = "${thresholds.high}-${thresholds.urgentHigh}",
                        percent = data.highPercent,
                    )
                    LegendEntry(
                        color = ColorUrgentHigh,
                        label = ">${thresholds.urgentHigh}",
                        percent = data.urgentHighPercent,
                    )
                }

                Spacer(modifier = Modifier.height(8.dp))

                // Target range
                Text(
                    text = "Target: ${thresholds.low}-${thresholds.high} mg/dL",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                    modifier = Modifier
                        .fillMaxWidth()
                        .testTag("tir_target_range"),
                )
            }
        }
    }
}

@Composable
private fun FiveBucketStackedBar(
    urgentLowPercent: Float,
    lowPercent: Float,
    inRangePercent: Float,
    highPercent: Float,
    urgentHighPercent: Float,
) {
    val barHeight = 24.dp
    val cornerRadius = 12.dp

    Canvas(
        modifier = Modifier
            .fillMaxWidth()
            .height(barHeight)
            .clip(RoundedCornerShape(cornerRadius)),
    ) {
        val totalWidth = size.width
        val h = size.height
        val cr = CornerRadius(cornerRadius.toPx())

        // Background
        drawRoundRect(
            color = Color(0xFF334155), // slate-700
            size = size,
            cornerRadius = cr,
        )

        val total = urgentLowPercent + lowPercent + inRangePercent + highPercent + urgentHighPercent
        if (total <= 0f) return@Canvas

        val segments = listOf(
            urgentLowPercent to ColorUrgentLow,
            lowPercent to ColorLow,
            inRangePercent to ColorInRange,
            highPercent to ColorHigh,
            urgentHighPercent to ColorUrgentHigh,
        )

        var x = 0f
        segments.forEachIndexed { index, (pct, color) ->
            if (pct <= 0f) return@forEachIndexed
            val w = if (index == segments.lastIndex) {
                totalWidth - x // absorb rounding on last segment
            } else {
                (pct / total) * totalWidth
            }
            if (w > 0f) {
                drawRect(
                    color = color,
                    topLeft = Offset(x, 0f),
                    size = Size(w, h),
                )
                x += w
            }
        }
    }
}

@Composable
private fun LegendEntry(
    color: Color,
    label: String,
    percent: Float,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .background(color, CircleShape),
        )
        Spacer(modifier = Modifier.width(4.dp))
        Text(
            text = "$label: ${formatTirPercent(percent)}",
            style = MaterialTheme.typography.labelSmall,
            color = color,
        )
    }
}

internal fun qualityAssessment(inRangePercent: Float): Pair<String, Color> = when {
    inRangePercent >= 70f -> "Excellent" to ColorInRange
    inRangePercent >= 50f -> "Good" to ColorHigh
    else -> "Needs Improvement" to ColorUrgentLow
}

internal fun formatTirPercent(value: Float): String = when {
    value <= 0f -> "0%"
    value < 0.5f -> "<1%"
    value >= 99.5f && value < 100f -> ">99%"
    else -> "%.0f%%".format(value)
}
