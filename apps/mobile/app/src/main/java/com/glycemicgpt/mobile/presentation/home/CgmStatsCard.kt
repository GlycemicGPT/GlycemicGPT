package com.glycemicgpt.mobile.presentation.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.domain.model.CgmStats
import com.glycemicgpt.mobile.presentation.theme.GlucoseColors

private val CgmStatsPeriods = listOf(
    TirPeriod.TWENTY_FOUR_HOURS,
    TirPeriod.THREE_DAYS,
    TirPeriod.SEVEN_DAYS,
)

@Composable
fun CgmStatsCard(
    stats: CgmStats?,
    selectedPeriod: TirPeriod,
    onPeriodSelected: (TirPeriod) -> Unit,
    maxRetentionDays: Int = AppSettingsStore.DEFAULT_RETENTION_DAYS,
    modifier: Modifier = Modifier,
) {
    val safeRetention = maxRetentionDays.coerceAtLeast(1)
    val availablePeriods = CgmStatsPeriods.filter { it.hours / 24 <= safeRetention }
    val effectivePeriod = if (selectedPeriod in availablePeriods) selectedPeriod else availablePeriods.first()
    val a11yDescription = if (stats != null) {
        ("CGM statistics: mean glucose %.0f mg/dL, std dev %.1f, " +
            "CV %.1f%%, GMI %.1f%%, CGM active %.0f%%, %d readings").format(
            stats.meanGlucose,
            stats.stdDev,
            stats.cvPercent,
            stats.gmi,
            stats.cgmActivePercent,
            stats.readingsCount,
        )
    } else {
        "CGM statistics: no data available"
    }

    Card(
        modifier = modifier
            .fillMaxWidth()
            .semantics { contentDescription = a11yDescription }
            .testTag("cgm_stats_card"),
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
                text = "CGM Stats",
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurface,
            )

            Spacer(modifier = Modifier.height(8.dp))

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
                        modifier = Modifier.testTag("cgm_stats_period_${period.label}"),
                    )
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            if (stats == null) {
                Text(
                    text = "No glucose readings for this period",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth(),
                )
            } else {
                // Row 1: Mean Glucose, Std Dev, CV%
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceEvenly,
                ) {
                    StatColumn(
                        label = "Mean Glucose",
                        value = "%.0f mg/dL".format(stats.meanGlucose),
                        valueColor = MaterialTheme.colorScheme.onSurface,
                    )
                    StatColumn(
                        label = "Std Dev",
                        value = "%.1f".format(stats.stdDev),
                        valueColor = MaterialTheme.colorScheme.onSurface,
                    )
                    val (cvLabel, cvColor) = cvAssessment(stats.cvPercent)
                    StatColumn(
                        label = "CV%",
                        value = "%.1f%%".format(stats.cvPercent),
                        valueColor = cvColor,
                        subtitle = cvLabel,
                    )
                }

                Spacer(modifier = Modifier.height(8.dp))

                // Row 2: GMI, CGM Active %, Readings
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceEvenly,
                ) {
                    StatColumn(
                        label = "GMI",
                        value = "%.1f%%".format(stats.gmi),
                        valueColor = MaterialTheme.colorScheme.onSurface,
                        subtitle = "est. A1C",
                    )
                    val (activeLabel, activeColor) = cgmActiveAssessment(stats.cgmActivePercent)
                    StatColumn(
                        label = "CGM Active",
                        value = "%.0f%%".format(stats.cgmActivePercent),
                        valueColor = activeColor,
                        subtitle = activeLabel,
                    )
                    StatColumn(
                        label = "Readings",
                        value = "%d".format(stats.readingsCount),
                        valueColor = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
        }
    }
}

@Composable
private fun StatColumn(
    label: String,
    value: String,
    valueColor: Color,
    subtitle: String? = null,
) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.SemiBold,
            color = valueColor,
        )
        if (subtitle != null) {
            Text(
                text = subtitle,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

internal fun cvAssessment(cvPercent: Float): Pair<String, Color> = when {
    cvPercent <= 36f -> "Stable" to GlucoseColors.InRange
    cvPercent <= 50f -> "Moderate" to GlucoseColors.High
    else -> "High" to GlucoseColors.UrgentHigh
}

internal fun cgmActiveAssessment(activePercent: Float): Pair<String, Color> = when {
    activePercent >= 70f -> "Good" to GlucoseColors.InRange
    activePercent >= 50f -> "Fair" to GlucoseColors.High
    else -> "Low" to GlucoseColors.UrgentHigh
}
