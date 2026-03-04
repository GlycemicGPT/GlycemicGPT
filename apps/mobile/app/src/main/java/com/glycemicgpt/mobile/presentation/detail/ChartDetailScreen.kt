package com.glycemicgpt.mobile.presentation.detail

import android.app.Activity
import android.content.pm.ActivityInfo
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.hilt.navigation.compose.hiltViewModel
import com.glycemicgpt.mobile.presentation.home.GlucoseTrendChart
import com.glycemicgpt.mobile.presentation.home.HomeViewModel
import timber.log.Timber

@Composable
fun ChartDetailScreen(
    onBack: () -> Unit,
    viewModel: HomeViewModel = hiltViewModel(),
) {
    val context = LocalContext.current
    DisposableEffect(Unit) {
        val activity = context as? Activity
        if (activity == null) {
            Timber.w("ChartDetailScreen: context is not an Activity, landscape lock skipped")
        }
        val original = activity?.requestedOrientation
        activity?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
        onDispose {
            activity?.requestedOrientation =
                original ?: ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
        }
    }

    val cgmHistory by viewModel.cgmHistory.collectAsState()
    val iobHistory by viewModel.iobHistory.collectAsState()
    val basalHistory by viewModel.basalHistory.collectAsState()
    val bolusHistory by viewModel.bolusHistory.collectAsState()
    val selectedPeriod by viewModel.selectedPeriod.collectAsState()
    val thresholds by viewModel.glucoseThresholds.collectAsState()

    DetailScaffold(title = "Glucose Trend", onBack = onBack) { padding ->
        GlucoseTrendChart(
            readings = cgmHistory,
            iobReadings = iobHistory,
            basalReadings = basalHistory,
            bolusEvents = bolusHistory,
            selectedPeriod = selectedPeriod,
            onPeriodSelected = { viewModel.onPeriodSelected(it) },
            thresholds = thresholds,
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        )
    }
}
