package com.glycemicgpt.mobile.presentation.detail

import android.app.Activity
import android.content.pm.ActivityInfo
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.glycemicgpt.mobile.presentation.home.AgpChart
import com.glycemicgpt.mobile.presentation.home.AgpPeriod
import com.glycemicgpt.mobile.presentation.home.HomeViewModel
import timber.log.Timber

@Composable
fun AgpDetailScreen(
    onBack: () -> Unit,
    viewModel: HomeViewModel = hiltViewModel(),
) {
    val context = LocalContext.current
    DisposableEffect(Unit) {
        val activity = context as? Activity
        if (activity == null) {
            Timber.w("AgpDetailScreen: context is not an Activity, landscape lock skipped")
        }
        val original = activity?.requestedOrientation
        activity?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
        onDispose {
            activity?.requestedOrientation =
                original ?: ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
        }
    }

    BackHandler(onBack = onBack)

    val agpProfile by viewModel.agpProfile.collectAsState()
    val selectedPeriod by viewModel.selectedAgpPeriod.collectAsState()
    val thresholds by viewModel.glucoseThresholds.collectAsState()

    Column(modifier = Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 4.dp, end = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack, modifier = Modifier.size(40.dp)) {
                Icon(
                    imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = "Back",
                    modifier = Modifier.size(18.dp),
                )
            }
            Text(
                text = "AGP Chart",
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Spacer(modifier = Modifier.width(12.dp))
            Row(
                modifier = Modifier.horizontalScroll(rememberScrollState()),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                AgpPeriod.entries.forEach { period ->
                    FilterChip(
                        selected = period == selectedPeriod,
                        onClick = { viewModel.onAgpPeriodSelected(period) },
                        label = {
                            Text(
                                text = period.label,
                                style = MaterialTheme.typography.labelMedium,
                            )
                        },
                        modifier = Modifier
                            .padding(horizontal = 3.dp)
                            .testTag("agp_detail_period_${period.label}"),
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor = MaterialTheme.colorScheme.primary,
                            selectedLabelColor = MaterialTheme.colorScheme.onPrimary,
                        ),
                    )
                }
            }
        }

        AgpChart(
            profile = agpProfile,
            selectedPeriod = selectedPeriod,
            onPeriodSelected = { viewModel.onAgpPeriodSelected(it) },
            thresholds = thresholds,
            isDetailMode = true,
            showPeriodSelector = false,
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 8.dp),
        )
    }
}
