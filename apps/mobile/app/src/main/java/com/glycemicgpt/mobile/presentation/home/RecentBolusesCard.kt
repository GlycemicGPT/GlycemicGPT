package com.glycemicgpt.mobile.presentation.home

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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.OpenInFull
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
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
import com.glycemicgpt.mobile.domain.model.BolusType
import com.glycemicgpt.mobile.domain.model.EnrichedBolusEvent
import com.glycemicgpt.mobile.presentation.theme.BolusTypeColors
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

private val BolusTimePeriods = listOf(
    TirPeriod.TWENTY_FOUR_HOURS,
    TirPeriod.THREE_DAYS,
    TirPeriod.SEVEN_DAYS,
)

private val BolusDateTimeFormatter: DateTimeFormatter =
    DateTimeFormatter.ofPattern("M/d h:mm a").withZone(ZoneId.systemDefault())

private const val MAX_HOME_ROWS = 5

@Composable
fun RecentBolusesCard(
    boluses: List<EnrichedBolusEvent>,
    selectedPeriod: TirPeriod,
    onPeriodSelected: (TirPeriod) -> Unit,
    categoryLabels: Map<String, String> = emptyMap(),
    onExpand: (() -> Unit)? = null,
    maxRetentionDays: Int = AppSettingsStore.DEFAULT_RETENTION_DAYS,
    modifier: Modifier = Modifier,
) {
    val safeRetention = maxRetentionDays.coerceAtLeast(1)
    val availablePeriods = BolusTimePeriods.filter { it.hours / 24 <= safeRetention }
    // Coerce period to one supported by this card
    val effectivePeriod = if (selectedPeriod in availablePeriods) selectedPeriod else availablePeriods.first()
    val a11yDescription = "Recent boluses: ${boluses.size} events in the last ${effectivePeriod.label}"

    Card(
        modifier = modifier
            .fillMaxWidth()
            .semantics { contentDescription = a11yDescription }
            .testTag("recent_boluses_card"),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface,
        ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
        ) {
            // Header
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "Recent Boluses",
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                if (onExpand != null) {
                    IconButton(
                        onClick = onExpand,
                        modifier = Modifier
                            .size(48.dp)
                            .testTag("expand_bolus_detail"),
                    ) {
                        Icon(
                            imageVector = Icons.Default.OpenInFull,
                            contentDescription = "View all boluses",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.size(20.dp),
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            // Period chips
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
                        modifier = Modifier.testTag("bolus_period_${period.label}"),
                    )
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            if (boluses.isEmpty()) {
                Text(
                    text = "No boluses for this period",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth(),
                )
            } else {
                // Table header
                BolusTableHeader()
                HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp))

                // Show most recent first, max 5 rows
                val recentBoluses = remember(boluses) {
                    boluses.sortedByDescending { it.timestamp }.take(MAX_HOME_ROWS)
                }
                recentBoluses.forEachIndexed { index, bolus ->
                    BolusTableRow(bolus, categoryLabels)
                    if (index < recentBoluses.lastIndex) {
                        HorizontalDivider(
                            modifier = Modifier.padding(vertical = 2.dp),
                            color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f),
                        )
                    }
                }

                if (boluses.size > MAX_HOME_ROWS && onExpand != null) {
                    Spacer(modifier = Modifier.height(4.dp))
                    TextButton(
                        onClick = onExpand,
                        modifier = Modifier
                            .fillMaxWidth()
                            .testTag("view_all_boluses"),
                    ) {
                        Text("View all ${boluses.size} boluses")
                    }
                }
            }
        }
    }
}

@Composable
internal fun BolusTableHeader() {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        TableHeaderCell("Time", Modifier.weight(1.2f))
        TableHeaderCell("Units", Modifier.weight(0.8f))
        TableHeaderCell("Type", Modifier.weight(1.2f))
        TableHeaderCell("BG", Modifier.weight(0.8f))
        TableHeaderCell("IoB", Modifier.weight(0.8f))
    }
}

@Composable
private fun TableHeaderCell(text: String, modifier: Modifier = Modifier) {
    Text(
        text = text,
        style = MaterialTheme.typography.labelSmall,
        fontWeight = FontWeight.SemiBold,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = modifier,
    )
}

@Composable
internal fun BolusTableRow(bolus: EnrichedBolusEvent, categoryLabels: Map<String, String> = emptyMap()) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 2.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = BolusDateTimeFormatter.format(bolus.timestamp),
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.weight(1.2f),
            )
            Text(
                text = String.format(Locale.US, "%.2fU", bolus.units),
                style = MaterialTheme.typography.bodySmall,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(0.8f),
            )
            Box(modifier = Modifier.weight(1.2f)) {
                BolusTypeBadge(bolus.bolusType, categoryLabels)
            }
            Text(
                text = bolus.bgAtEvent?.toString() ?: "--",
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.weight(0.8f),
            )
            Text(
                text = bolus.iobAtEvent?.let { String.format(Locale.US, "%.1fU", it) } ?: "--",
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.weight(0.8f),
            )
        }
        Text(
            text = bolus.reason,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(start = 2.dp, top = 1.dp),
        )
    }
}

@Composable
private fun BolusTypeBadge(type: BolusType, categoryLabels: Map<String, String> = emptyMap()) {
    // AUTO has no dedicated BolusCategory -- always use static "Auto" to avoid
    // conflating with AUTO_CORRECTION when users customize labels.
    val (label, color) = when (type) {
        BolusType.AUTO_CORRECTION -> (categoryLabels["AUTO_CORRECTION"] ?: "Auto Corr") to BolusTypeColors.Correction
        BolusType.CORRECTION -> (categoryLabels["CORRECTION"] ?: "Correction") to BolusTypeColors.ManualCorrection
        BolusType.MEAL -> (categoryLabels["FOOD"] ?: "Meal") to BolusTypeColors.Meal
        BolusType.MEAL_WITH_CORRECTION -> (categoryLabels["FOOD_AND_CORRECTION"] ?: "Meal+Corr") to BolusTypeColors.MealWithCorrection
        BolusType.AUTO -> "Auto" to BolusTypeColors.Correction
    }

    Text(
        text = label,
        style = MaterialTheme.typography.labelSmall,
        fontWeight = FontWeight.SemiBold,
        color = Color.White,
        maxLines = 1,
        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
        modifier = Modifier
            .background(color.copy(alpha = 0.85f), RoundedCornerShape(4.dp))
            .padding(horizontal = 6.dp, vertical = 1.dp),
    )
}
