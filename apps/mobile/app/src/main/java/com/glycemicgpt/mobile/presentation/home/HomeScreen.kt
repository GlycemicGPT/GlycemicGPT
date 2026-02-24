package com.glycemicgpt.mobile.presentation.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bluetooth
import androidx.compose.material.icons.filled.BluetoothConnected
import androidx.compose.material.icons.filled.BluetoothDisabled
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.CloudSync
import androidx.compose.material.icons.automirrored.filled.BluetoothSearching
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.plugin.ui.DashboardCardDescriptor
import com.glycemicgpt.mobile.presentation.plugin.PluginDashboardCardRenderer
import com.glycemicgpt.mobile.presentation.theme.GlucoseColors
import com.glycemicgpt.mobile.service.SyncStatus
import kotlinx.coroutines.delay
import java.time.Instant

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    viewModel: HomeViewModel = hiltViewModel(),
) {
    val connectionState by viewModel.connectionState.collectAsState()
    val cgm by viewModel.cgm.collectAsState()
    val iob by viewModel.iob.collectAsState()
    val basalRate by viewModel.basalRate.collectAsState()
    val battery by viewModel.battery.collectAsState()
    val reservoir by viewModel.reservoir.collectAsState()
    val syncStatus by viewModel.syncStatus.collectAsState()
    val isRefreshing by viewModel.isRefreshing.collectAsState()
    val selectedPeriod by viewModel.selectedPeriod.collectAsState()
    val cgmHistory by viewModel.cgmHistory.collectAsState()
    val iobHistory by viewModel.iobHistory.collectAsState()
    val basalHistory by viewModel.basalHistory.collectAsState()
    val bolusHistory by viewModel.bolusHistory.collectAsState()
    val selectedTirPeriod by viewModel.selectedTirPeriod.collectAsState()
    val timeInRange by viewModel.timeInRange.collectAsState()
    val thresholds by viewModel.glucoseThresholds.collectAsState()
    val pluginCards by viewModel.pluginCards.collectAsState()

    PullToRefreshBox(
        isRefreshing = isRefreshing,
        onRefresh = { viewModel.refreshData() },
        modifier = Modifier.fillMaxSize(),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            // Compact connection + sync status row
            ConnectionSyncRow(connectionState, syncStatus)

            Spacer(modifier = Modifier.height(12.dp))

            // Glucose hero: large current BG + trend + IoB + Basal + Battery + Reservoir
            GlucoseHero(
                cgm = cgm,
                iob = iob,
                basalRate = basalRate,
                battery = battery,
                reservoir = reservoir,
                thresholds = thresholds,
            )

            Spacer(modifier = Modifier.height(12.dp))

            // Glucose trend chart with IoB, basal, and bolus overlays
            GlucoseTrendChart(
                readings = cgmHistory,
                iobReadings = iobHistory,
                basalReadings = basalHistory,
                bolusEvents = bolusHistory,
                selectedPeriod = selectedPeriod,
                onPeriodSelected = { viewModel.onPeriodSelected(it) },
                thresholds = thresholds,
            )

            Spacer(modifier = Modifier.height(12.dp))

            // Time in Range bar
            TimeInRangeBar(
                data = timeInRange,
                selectedPeriod = selectedTirPeriod,
                onPeriodSelected = { viewModel.onTirPeriodSelected(it) },
                thresholds = thresholds,
            )

            // Plugin-contributed cards (sorted by priority, memoized)
            val sortedCards = remember(pluginCards) { pluginCards.sortedBy { it.priority } }
            if (sortedCards.isNotEmpty()) {
                sortedCards.forEach { card ->
                    Spacer(modifier = Modifier.height(12.dp))
                    PluginDashboardCardRenderer(card = card)
                }
            }


            Spacer(modifier = Modifier.height(24.dp))

            if (connectionState == ConnectionState.DISCONNECTED) {
                Text(
                    text = "Pair your pump in Settings to start",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else if (connectionState == ConnectionState.CONNECTED && cgm == null) {
                Text(
                    text = "Loading pump data...",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.tertiary,
                )
            }
        }
    }
}

@Composable
private fun ConnectionSyncRow(state: ConnectionState, syncStatus: SyncStatus) {
    val (bleIcon, bleA11y, bleColor, bleText) = when (state) {
        ConnectionState.CONNECTED -> Quad(
            Icons.Default.BluetoothConnected,
            "Pump connected",
            MaterialTheme.colorScheme.primary,
            null,
        )
        ConnectionState.CONNECTING, ConnectionState.AUTHENTICATING -> Quad(
            Icons.AutoMirrored.Filled.BluetoothSearching,
            "Connecting to pump",
            MaterialTheme.colorScheme.tertiary,
            "Connecting...",
        )
        ConnectionState.RECONNECTING -> Quad(
            Icons.Default.Bluetooth,
            "Reconnecting to pump",
            MaterialTheme.colorScheme.tertiary,
            "Reconnecting...",
        )
        ConnectionState.SCANNING -> Quad(
            Icons.AutoMirrored.Filled.BluetoothSearching,
            "Scanning for pump",
            MaterialTheme.colorScheme.tertiary,
            "Scanning...",
        )
        ConnectionState.AUTH_FAILED -> Quad(
            Icons.Default.BluetoothDisabled,
            "Pump pairing failed",
            MaterialTheme.colorScheme.error,
            "Pairing failed",
        )
        ConnectionState.DISCONNECTED -> Quad(
            Icons.Default.BluetoothDisabled,
            "No pump connected",
            MaterialTheme.colorScheme.error,
            null,
        )
    }

    val (syncIcon, syncA11y, syncColor) = when {
        syncStatus.lastError != null -> Triple(
            Icons.Default.CloudOff,
            "Sync error",
            MaterialTheme.colorScheme.error,
        )
        syncStatus.pendingCount > 0 -> Triple(
            Icons.Default.CloudSync,
            "${syncStatus.pendingCount} readings pending sync",
            MaterialTheme.colorScheme.tertiary,
        )
        syncStatus.lastSyncAtMs > 0 -> Triple(
            Icons.Default.CloudDone,
            "Synced to cloud",
            MaterialTheme.colorScheme.primary,
        )
        else -> Triple(
            Icons.Default.CloudOff,
            "Not synced",
            MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("connection_status"),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = bleIcon,
            contentDescription = bleA11y,
            tint = bleColor,
            modifier = Modifier.size(16.dp),
        )
        if (bleText != null) {
            Spacer(modifier = Modifier.width(4.dp))
            Text(
                text = bleText,
                style = MaterialTheme.typography.labelSmall,
                color = bleColor,
            )
        }
        Spacer(modifier = Modifier.width(12.dp))
        Icon(
            imageVector = syncIcon,
            contentDescription = syncA11y,
            tint = syncColor,
            modifier = Modifier.size(16.dp),
        )
    }
}

private data class Quad<A, B, C, D>(val first: A, val second: B, val third: C, val fourth: D)

@Composable
internal fun FreshnessLabel(timestamp: Instant) {
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) {
        while (true) {
            delay(30_000)
            now = System.currentTimeMillis()
        }
    }

    val ageSeconds = (now - timestamp.toEpochMilli()) / 1000
    val label = when {
        ageSeconds < 60 -> "just now"
        ageSeconds < 3600 -> "${ageSeconds / 60}m ago"
        ageSeconds < 86400 -> "${ageSeconds / 3600}h ago"
        else -> "stale"
    }

    val color = when {
        ageSeconds < 120 -> GlucoseColors.InRange
        ageSeconds < 600 -> GlucoseColors.High
        else -> GlucoseColors.UrgentHigh
    }

    Text(
        text = label,
        style = MaterialTheme.typography.labelSmall,
        color = color,
    )
}
