package com.glycemicgpt.mobile.presentation.detail

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.glycemicgpt.mobile.presentation.home.BolusTableHeader
import com.glycemicgpt.mobile.presentation.home.BolusTableRow
import com.glycemicgpt.mobile.presentation.home.HomeViewModel
import com.glycemicgpt.mobile.presentation.home.TirPeriod

@Composable
fun BolusHistoryScreen(
    onBack: () -> Unit,
    viewModel: HomeViewModel = hiltViewModel(),
) {
    BackHandler(onBack = onBack)

    val enrichedBoluses by viewModel.enrichedBoluses.collectAsState()
    val selectedPeriod by viewModel.selectedBolusPeriod.collectAsState()

    DetailScaffold(title = "Bolus History", onBack = onBack) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(horizontal = 16.dp),
        ) {
            Spacer(modifier = Modifier.height(8.dp))

            // All 5 period options
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
            ) {
                TirPeriod.entries.forEach { period ->
                    FilterChip(
                        selected = period == selectedPeriod,
                        onClick = { viewModel.onBolusPeriodSelected(period) },
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
                        modifier = Modifier.testTag("bolus_history_period_${period.label}"),
                    )
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            if (enrichedBoluses.isEmpty()) {
                Text(
                    text = "No boluses for this period",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 32.dp),
                )
            } else {
                BolusTableHeader()
                HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp))

                val sorted = remember(enrichedBoluses) {
                    enrichedBoluses.sortedByDescending { it.timestamp }
                }

                LazyColumn(
                    modifier = Modifier
                        .fillMaxSize()
                        .testTag("bolus_history_list"),
                ) {
                    items(sorted.size) { index ->
                        val bolus = sorted[index]
                        BolusTableRow(bolus)
                        HorizontalDivider(
                            modifier = Modifier.padding(vertical = 2.dp),
                            color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f),
                        )
                    }
                }
            }
        }
    }
}
