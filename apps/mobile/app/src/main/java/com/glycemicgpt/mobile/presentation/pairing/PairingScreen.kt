package com.glycemicgpt.mobile.presentation.pairing

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bluetooth
import androidx.compose.material.icons.filled.BluetoothSearching
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.LinkOff
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.hilt.navigation.compose.hiltViewModel
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.model.DiscoveredPump
import com.glycemicgpt.mobile.domain.model.TandemPumpModel

@Composable
fun PairingScreen(
    viewModel: PairingViewModel = hiltViewModel(),
    onPaired: () -> Unit = {},
) {
    val discoveredPumps by viewModel.discoveredPumps.collectAsState()
    val isScanning by viewModel.isScanning.collectAsState()
    val selectedPump by viewModel.selectedPump.collectAsState()
    val pairingCode by viewModel.pairingCode.collectAsState()
    val connectionState by viewModel.connectionState.collectAsState()

    LaunchedEffect(connectionState) {
        if (connectionState == ConnectionState.CONNECTED) {
            onPaired()
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
    ) {
        Text(
            text = "Pump Pairing",
            style = MaterialTheme.typography.headlineMedium,
        )

        Spacer(modifier = Modifier.height(8.dp))

        // Show current pairing status
        if (viewModel.isPaired) {
            PairedStatusCard(
                address = viewModel.pairedAddress ?: "",
                connectionState = connectionState,
                onUnpair = { viewModel.unpair() },
            )
            Spacer(modifier = Modifier.height(16.dp))
        }

        when {
            // Connecting/authenticating state
            connectionState == ConnectionState.CONNECTING ||
                connectionState == ConnectionState.AUTHENTICATING -> {
                ConnectingCard(connectionState)
            }

            // Auth failed -- show error with retry option
            connectionState == ConnectionState.AUTH_FAILED && selectedPump != null -> {
                AuthFailedCard(onRetry = { viewModel.pair() })
                Spacer(modifier = Modifier.height(16.dp))
                PairingCodeInput(
                    pump = selectedPump!!,
                    pairingCode = pairingCode,
                    onCodeChanged = { viewModel.updatePairingCode(it) },
                    onPair = { viewModel.pair() },
                    onCancel = { viewModel.clearSelection() },
                )
            }

            // Pump selected, show pairing code input
            selectedPump != null -> {
                PairingCodeInput(
                    pump = selectedPump!!,
                    pairingCode = pairingCode,
                    onCodeChanged = { viewModel.updatePairingCode(it) },
                    onPair = { viewModel.pair() },
                    onCancel = { viewModel.clearSelection() },
                )
            }

            // Scan mode
            else -> {
                ScanSection(
                    pumps = discoveredPumps,
                    isScanning = isScanning,
                    onStartScan = { viewModel.startScan() },
                    onStopScan = { viewModel.stopScan() },
                    onSelectPump = { viewModel.selectPump(it) },
                )
            }
        }
    }
}

@Composable
private fun PairedStatusCard(
    address: String,
    connectionState: ConnectionState,
    onUnpair: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer,
        ),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = if (connectionState == ConnectionState.CONNECTED) {
                    Icons.Default.CheckCircle
                } else {
                    Icons.Default.Bluetooth
                },
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onPrimaryContainer,
            )
            Spacer(modifier = Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = if (connectionState == ConnectionState.CONNECTED) "Connected" else "Paired",
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                )
                Text(
                    text = address,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                )
            }
            OutlinedButton(onClick = onUnpair) {
                Icon(Icons.Default.LinkOff, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(modifier = Modifier.width(4.dp))
                Text("Unpair")
            }
        }
    }
}

@Composable
private fun AuthFailedCard(onRetry: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.errorContainer,
        ),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "Pairing failed",
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onErrorContainer,
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = "The pump rejected the pairing attempt. Please verify the " +
                    "code and try again.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onErrorContainer,
            )
        }
    }
}

@Composable
private fun ConnectingCard(state: ConnectionState) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .padding(32.dp),
            contentAlignment = Alignment.Center,
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                CircularProgressIndicator()
                Spacer(modifier = Modifier.height(16.dp))
                Text(
                    text = when (state) {
                        ConnectionState.CONNECTING -> "Connecting to pump..."
                        ConnectionState.AUTHENTICATING -> "Authenticating..."
                        else -> "Working..."
                    },
                    style = MaterialTheme.typography.bodyLarge,
                )
            }
        }
    }
}

@Composable
private fun PairingCodeInput(
    pump: DiscoveredPump,
    pairingCode: String,
    onCodeChanged: (String) -> Unit,
    onPair: () -> Unit,
    onCancel: () -> Unit,
) {
    val pumpModel = remember(pump.name) { TandemPumpModel.fromAdvertisedName(pump.name) }
    val instructionText = when (pumpModel.hasScreen) {
        true -> "Check your pump screen for the pairing code. " +
            "You must confirm pairing on the pump."
        false -> "Put your Mobi on the charging pad and double-press the " +
            "pump button to enter pairing mode. Then enter the 6-digit PIN " +
            "printed behind the cartridge well on your pump body."
        null -> "Enter the pairing code from your pump. Check your pump " +
            "screen or documentation for the code."
    }

    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "Enter Pairing Code",
                style = MaterialTheme.typography.titleMedium,
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = instructionText,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = "${pump.name} (${pump.address})",
                style = MaterialTheme.typography.bodyMedium,
            )
            Spacer(modifier = Modifier.height(16.dp))
            OutlinedTextField(
                value = pairingCode,
                onValueChange = onCodeChanged,
                label = { Text("Pairing Code") },
                modifier = Modifier.fillMaxWidth().testTag("pairing_code_field"),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text),
                singleLine = true,
            )
            Spacer(modifier = Modifier.height(16.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedButton(
                    onClick = onCancel,
                    modifier = Modifier.weight(1f),
                ) {
                    Text("Cancel")
                }
                Button(
                    onClick = onPair,
                    modifier = Modifier.weight(1f).testTag("pair_button"),
                    enabled = pairingCode.length >= 6,
                ) {
                    Text("Pair")
                }
            }
        }
    }
}

private fun requiredBlePermissions(): Array<String> =
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        arrayOf(
            Manifest.permission.BLUETOOTH_SCAN,
            Manifest.permission.BLUETOOTH_CONNECT,
        )
    } else {
        arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
    }

@Composable
private fun ScanSection(
    pumps: List<DiscoveredPump>,
    isScanning: Boolean,
    onStartScan: () -> Unit,
    onStopScan: () -> Unit,
    onSelectPump: (DiscoveredPump) -> Unit,
) {
    val context = LocalContext.current
    var permissionDenied by remember { mutableStateOf(false) }

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestMultiplePermissions(),
    ) { results ->
        val allGranted = results.values.all { it }
        if (allGranted) {
            permissionDenied = false
            onStartScan()
        } else {
            permissionDenied = true
        }
    }

    fun hasPermissions(): Boolean {
        return requiredBlePermissions().all { perm ->
            ContextCompat.checkSelfPermission(context, perm) == PackageManager.PERMISSION_GRANTED
        }
    }

    Text(
        text = "Scan for nearby Tandem pumps. Make sure Bluetooth is enabled " +
            "and your pump is in pairing mode.",
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Spacer(modifier = Modifier.height(16.dp))

    if (permissionDenied) {
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.errorContainer,
            ),
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(
                    text = "Bluetooth permissions required",
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onErrorContainer,
                )
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = "GlycemicGPT needs Bluetooth permissions to scan for and " +
                        "connect to your Tandem pump. Please grant the permissions " +
                        "when prompted, or enable them in your device settings.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onErrorContainer,
                )
            }
        }
        Spacer(modifier = Modifier.height(8.dp))
    }

    Button(
        onClick = if (isScanning) {
            onStopScan
        } else {
            {
                if (hasPermissions()) {
                    permissionDenied = false
                    onStartScan()
                } else {
                    permissionLauncher.launch(requiredBlePermissions())
                }
            }
        },
        modifier = Modifier.fillMaxWidth().testTag("scan_button"),
    ) {
        Icon(
            imageVector = Icons.Default.BluetoothSearching,
            contentDescription = null,
            modifier = Modifier.size(20.dp),
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(if (isScanning) "Stop Scan" else "Scan for Pumps")
    }

    if (isScanning) {
        Spacer(modifier = Modifier.height(8.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
            Spacer(modifier = Modifier.width(8.dp))
            Text("Scanning...", style = MaterialTheme.typography.bodySmall)
        }
    }

    Spacer(modifier = Modifier.height(16.dp))

    if (pumps.isEmpty() && !isScanning) {
        Text(
            text = "No pumps found. Tap Scan to search.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }

    LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items(pumps) { pump ->
            PumpCard(pump = pump, onClick = { onSelectPump(pump) })
        }
    }
}

@Composable
private fun PumpCard(pump: DiscoveredPump, onClick: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = Icons.Default.Bluetooth,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
            )
            Spacer(modifier = Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = pump.name,
                    style = MaterialTheme.typography.titleSmall,
                )
                Text(
                    text = pump.address,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                text = "${pump.rssi} dBm",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
