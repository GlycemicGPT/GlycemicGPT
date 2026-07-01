package com.glycemicgpt.mobile.presentation.debug

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import com.glycemicgpt.mobile.data.local.BleDebugStore
import com.glycemicgpt.mobile.domain.model.ConnectionState
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private val timeFormatter = DateTimeFormatter.ofPattern("HH:mm:ss.SSS")
    .withZone(ZoneId.systemDefault())

@Composable
fun BleDebugScreen(
    viewModel: BleDebugViewModel = hiltViewModel(),
) {
    val entries by viewModel.entries.collectAsState()
    val connectionState by viewModel.connectionState.collectAsState()
    val listState = rememberLazyListState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                text = "BLE Debug",
                style = MaterialTheme.typography.headlineMedium,
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                // Debug harness: seed a fresh CGM reading so the emulator (no live
                // pump feed) can render the glucose hero and exercise the staleness/de-emphasis path.
                OutlinedButton(
                    onClick = viewModel::injectTestCgm,
                    modifier = Modifier.testTag("inject_test_cgm_button"),
                ) {
                    Text("Inject CGM")
                }
                Spacer(modifier = Modifier.width(8.dp))
                OutlinedButton(onClick = viewModel::clearEntries) {
                    Text("Clear")
                }
            }
        }

        Spacer(modifier = Modifier.height(8.dp))

        // Connection state indicator
        ConnectionStateBar(connectionState)

        Spacer(modifier = Modifier.height(8.dp))

        Text(
            text = "${entries.size} entries",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.testTag("debug_entry_count"),
        )

        Spacer(modifier = Modifier.height(8.dp))

        // Entries list (newest first)
        LazyColumn(
            state = listState,
            verticalArrangement = Arrangement.spacedBy(6.dp),
            modifier = Modifier.testTag("debug_entries_list"),
        ) {
            items(entries.reversed()) { entry ->
                DebugEntryCard(entry)
            }
        }
    }
}

@Composable
private fun ConnectionStateBar(state: ConnectionState) {
    val color = when (state) {
        ConnectionState.CONNECTED -> MaterialTheme.colorScheme.primary
        ConnectionState.SCANNING, ConnectionState.CONNECTING, ConnectionState.AUTHENTICATING ->
            MaterialTheme.colorScheme.tertiary
        ConnectionState.RECONNECTING -> MaterialTheme.colorScheme.secondary
        ConnectionState.DISCONNECTED -> MaterialTheme.colorScheme.error
        ConnectionState.AUTH_FAILED -> MaterialTheme.colorScheme.error
    }

    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.testTag("debug_connection_state"),
    ) {
        Spacer(
            modifier = Modifier
                .size(10.dp)
                .clip(CircleShape)
                .background(color),
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(
            text = state.name,
            style = MaterialTheme.typography.bodyMedium,
            color = color,
        )
    }
}

@Composable
private fun DebugEntryCard(entry: BleDebugStore.Entry) {
    val dirColor = when (entry.direction) {
        BleDebugStore.Direction.TX -> MaterialTheme.colorScheme.primary
        BleDebugStore.Direction.RX -> MaterialTheme.colorScheme.tertiary
    }
    val dirLabel = when (entry.direction) {
        BleDebugStore.Direction.TX -> "TX"
        BleDebugStore.Direction.RX -> "RX"
    }

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
        ),
    ) {
        Column(modifier = Modifier.padding(10.dp)) {
            // Header row: direction, opcode, time
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = dirLabel,
                        style = MaterialTheme.typography.labelSmall,
                        color = dirColor,
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        text = entry.opcodeName,
                        style = MaterialTheme.typography.bodySmall,
                    )
                    Spacer(modifier = Modifier.width(4.dp))
                    Text(
                        text = "(0x${entry.opcode.toString(16).padStart(2, '0')})",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        fontFamily = FontFamily.Monospace,
                        fontSize = 11.sp,
                    )
                }
                Text(
                    text = timeFormatter.format(entry.timestamp),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 11.sp,
                )
            }

            // txId + cargo size
            Text(
                text = "txId=${entry.txId}  cargo=${entry.cargoSize}B",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontFamily = FontFamily.Monospace,
                fontSize = 11.sp,
            )

            // Cargo hex (horizontally scrollable for long payloads)
            if (entry.cargoHex.isNotEmpty()) {
                HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp))
                Text(
                    text = entry.cargoHex,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 11.sp,
                    color = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.horizontalScroll(rememberScrollState()),
                )
            }

            // Parsed value or error
            entry.parsedValue?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
            entry.error?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }
    }
}
