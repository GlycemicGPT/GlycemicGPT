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
import androidx.compose.material3.HorizontalDivider
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
import com.glycemicgpt.mobile.domain.model.BolusCategory
import com.glycemicgpt.mobile.domain.model.InsulinSummary
import com.glycemicgpt.mobile.presentation.theme.colorForCategory
import java.util.Locale

private val BasalColor = Color(0xFF38BDF8)  // sky-400
private val BolusColor = Color(0xFF8B5CF6)  // violet-500

private val InsulinPeriods = listOf(
    TirPeriod.TWENTY_FOUR_HOURS,
    TirPeriod.THREE_DAYS,
    TirPeriod.SEVEN_DAYS,
)

/** Display order for category rows in the breakdown section. */
private val CATEGORY_DISPLAY_ORDER = listOf(
    BolusCategory.FOOD_AND_CORRECTION,
    BolusCategory.CORRECTION,
    BolusCategory.FOOD,
    BolusCategory.AUTO_CORRECTION,
    BolusCategory.OVERRIDE,
    BolusCategory.AI_SUGGESTED,
    BolusCategory.OTHER,
)

@Composable
fun InsulinSummaryCard(
    summary: InsulinSummary?,
    selectedPeriod: TirPeriod,
    onPeriodSelected: (TirPeriod) -> Unit,
    modifier: Modifier = Modifier,
) {
    // Coerce period to one supported by this card (other cards may allow 14D/30D)
    val effectivePeriod = if (selectedPeriod in InsulinPeriods) selectedPeriod else InsulinPeriods.first()

    val a11yDescription = if (summary != null) {
        String.format(
            Locale.US,
            "Insulin summary: total daily dose %.1f units, " +
                "basal %.1f units (%.0f%%), bolus %.1f units (%.0f%%). " +
                "Food bolus %.1f, Correction bolus %.1f units per day. " +
                "%d total boluses",
            summary.totalDailyDose,
            summary.basalUnits,
            summary.basalPercent,
            summary.bolusUnits,
            summary.bolusPercent,
            summary.foodBolusUnits,
            summary.correctionBolusUnits,
            summary.bolusCount,
        )
    } else {
        "Insulin summary: no data available"
    }

    Card(
        modifier = modifier
            .fillMaxWidth()
            .semantics { contentDescription = a11yDescription }
            .testTag("insulin_summary_card"),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface,
        ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
        ) {
            Text(
                text = "Insulin Summary",
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurface,
            )

            Spacer(modifier = Modifier.height(8.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
            ) {
                InsulinPeriods.forEach { period ->
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
                        modifier = Modifier.testTag("insulin_period_${period.label}"),
                    )
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            if (summary == null) {
                Text(
                    text = "No insulin data for this period",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth(),
                )
            } else {
                // TDD large value
                Text(
                    text = String.format(Locale.US, "%.1f U/day", summary.totalDailyDose),
                    style = MaterialTheme.typography.headlineMedium,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.fillMaxWidth(),
                    textAlign = TextAlign.Center,
                )

                Spacer(modifier = Modifier.height(8.dp))

                // Stacked bar
                InsulinStackedBar(
                    basalPercent = summary.basalPercent,
                    bolusPercent = summary.bolusPercent,
                )

                Spacer(modifier = Modifier.height(8.dp))

                // Legend
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceEvenly,
                ) {
                    InsulinLegend(
                        color = BasalColor,
                        label = "Basal",
                        value = String.format(Locale.US, "%.1fU (%.0f%%)", summary.basalUnits, summary.basalPercent),
                    )
                    InsulinLegend(
                        color = BolusColor,
                        label = "Bolus",
                        value = String.format(Locale.US, "%.1fU (%.0f%%)", summary.bolusUnits, summary.bolusPercent),
                    )
                }

                Spacer(modifier = Modifier.height(8.dp))
                HorizontalDivider(
                    color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f),
                )
                Spacer(modifier = Modifier.height(8.dp))

                // Portion-based delivery totals
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .testTag("insulin_detail_stats"),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    PortionRow(
                        label = "Food Bolus",
                        value = String.format(Locale.US, "%.1f U/d", summary.foodBolusUnits),
                    )
                    PortionRow(
                        label = "Correction Bolus",
                        value = String.format(Locale.US, "%.1f U/d", summary.correctionBolusUnits),
                    )
                }

                // Category breakdown (only if we have categories)
                if (summary.categoryBreakdown.isNotEmpty()) {
                    Spacer(modifier = Modifier.height(8.dp))
                    HorizontalDivider(
                        color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f),
                    )
                    Spacer(modifier = Modifier.height(8.dp))

                    // Total count header
                    Text(
                        text = "${summary.bolusCount} boluses",
                        style = MaterialTheme.typography.bodySmall,
                        fontWeight = FontWeight.SemiBold,
                        color = MaterialTheme.colorScheme.onSurface,
                    )

                    Spacer(modifier = Modifier.height(4.dp))

                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .testTag("insulin_category_breakdown"),
                        verticalArrangement = Arrangement.spacedBy(2.dp),
                    ) {
                        for (category in CATEGORY_DISPLAY_ORDER) {
                            val stats = summary.categoryBreakdown[category] ?: continue
                            val pct = if (summary.bolusCount > 0) {
                                (stats.count * 100f / summary.bolusCount)
                            } else {
                                0f
                            }
                            CategoryCountRow(
                                color = colorForCategory(category),
                                label = category.displayName,
                                count = stats.count,
                                percent = pct,
                            )
                        }
                    }
                } else {
                    // Fallback: simple count footer when no category data
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = "${summary.bolusCount} boluses (${summary.correctionCount} corrections)",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        }
    }
}

@Composable
private fun InsulinStackedBar(
    basalPercent: Float,
    bolusPercent: Float,
) {
    val barHeight = 24.dp
    val cornerRadius = 12.dp

    Canvas(
        modifier = Modifier
            .fillMaxWidth()
            .height(barHeight)
            .clip(RoundedCornerShape(cornerRadius))
            .testTag("insulin_stacked_bar"),
    ) {
        val totalWidth = size.width
        val h = size.height
        val cr = CornerRadius(cornerRadius.toPx())

        drawRoundRect(
            color = Color(0xFF334155),
            size = size,
            cornerRadius = cr,
        )

        val safeBasal = basalPercent.coerceAtLeast(0f)
        val safeBolus = bolusPercent.coerceAtLeast(0f)
        val total = safeBasal + safeBolus
        if (total <= 0f) return@Canvas

        val basalW = (safeBasal / total) * totalWidth
        val bolusW = totalWidth - basalW

        if (basalW > 0f) {
            drawRect(
                color = BasalColor,
                topLeft = Offset(0f, 0f),
                size = Size(basalW, h),
            )
        }
        if (bolusW > 0f) {
            drawRect(
                color = BolusColor,
                topLeft = Offset(basalW, 0f),
                size = Size(bolusW, h),
            )
        }
    }
}

@Composable
private fun InsulinLegend(
    color: Color,
    label: String,
    value: String,
) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .background(color, CircleShape),
        )
        Spacer(modifier = Modifier.width(4.dp))
        Column {
            Text(
                text = label,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                text = value,
                style = MaterialTheme.typography.bodySmall,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
            )
        }
    }
}

@Composable
private fun PortionRow(
    label: String,
    value: String,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .semantics(mergeDescendants = true) {
                contentDescription = "$label: $value"
            },
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodySmall,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
}

@Composable
private fun CategoryCountRow(
    color: Color,
    label: String,
    count: Int,
    percent: Float,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .semantics(mergeDescendants = true) {
                contentDescription = "$label: $count (${String.format(Locale.US, "%.0f", percent)}%)"
            },
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.weight(1f),
        ) {
            Box(
                modifier = Modifier
                    .size(8.dp)
                    .background(color, CircleShape),
            )
            Spacer(modifier = Modifier.width(6.dp))
            Text(
                text = label,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Text(
            text = String.format(Locale.US, "%d", count),
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.width(28.dp),
            textAlign = TextAlign.End,
        )
        Text(
            text = String.format(Locale.US, "%3.0f%%", percent),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.width(36.dp),
            textAlign = TextAlign.End,
        )
    }
}
