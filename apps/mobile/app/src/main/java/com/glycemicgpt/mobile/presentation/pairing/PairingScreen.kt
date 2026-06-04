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
import com.glycemicgpt.mobile.domain.plugin.PairingFault
import com.glycemicgpt.mobile.domain.plugin.PairingStyle

@Composable
fun PairingScreen(
    viewModel: PairingViewModel = hiltViewModel(),
    onPaired: () -> Unit = {},
) {
    val discoveredPumps by viewModel.discoveredPumps.collectAsState()
    val isScanning by viewModel.isScanning.collectAsState()
    val isAdvertising by viewModel.isAdvertising.collectAsState()
    val selectedPump by viewModel.selectedPump.collectAsState()
    val pairingCode by viewModel.pairingCode.collectAsState()
    val connectionState by viewModel.connectionState.collectAsState()
    val pairingProfile by viewModel.pairingProfile.collectAsState()
    val pairingFault by viewModel.pairingFault.collectAsState()

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

        // The active plugin's topology decides the flow: central-scan (phone scans, lists devices) vs
        // advertise-and-wait (phone advertises, the device connects to it). Generalized off the plugin
        // so each pump drives its own pairing UX through the same screen.
        when (pairingProfile.style) {
            PairingStyle.CENTRAL_SCAN -> CentralScanContent(
                discoveredPumps = discoveredPumps,
                isScanning = isScanning,
                selectedPump = selectedPump,
                pairingCode = pairingCode,
                connectionState = connectionState,
                onStartScan = { viewModel.startScan() },
                onStopScan = { viewModel.stopScan() },
                onSelectPump = { viewModel.selectPump(it) },
                onCodeChanged = { viewModel.updatePairingCode(it) },
                onPair = { viewModel.pair() },
                onCancelSelection = { viewModel.clearSelection() },
            )

            PairingStyle.ADVERTISE_AND_WAIT -> AdvertiseAndWaitContent(
                advertisedName = pairingProfile.advertisedName,
                isAdvertising = isAdvertising,
                connectionState = connectionState,
                fault = pairingFault,
                onStartAdvertising = { viewModel.startAdvertising() },
                onStopAdvertising = { viewModel.stopAdvertising() },
            )
        }
    }
}

/**
 * Central-scan pairing (phone is the BLE central): scan, list nearby pumps, tap one, enter the code.
 * Unchanged Tandem flow, lifted into its own composable so the screen can branch by [PairingStyle].
 */
@Composable
private fun CentralScanContent(
    discoveredPumps: List<DiscoveredPump>,
    isScanning: Boolean,
    selectedPump: DiscoveredPump?,
    pairingCode: String,
    connectionState: ConnectionState,
    onStartScan: () -> Unit,
    onStopScan: () -> Unit,
    onSelectPump: (DiscoveredPump) -> Unit,
    onCodeChanged: (String) -> Unit,
    onPair: () -> Unit,
    onCancelSelection: () -> Unit,
) {
    when {
        // Connecting/authenticating state
        connectionState == ConnectionState.CONNECTING ||
            connectionState == ConnectionState.AUTHENTICATING -> {
            ConnectingCard(connectionState)
        }

        // Auth failed -- show error with retry option
        connectionState == ConnectionState.AUTH_FAILED && selectedPump != null -> {
            AuthFailedCard(onRetry = onPair)
            Spacer(modifier = Modifier.height(16.dp))
            PairingCodeInput(
                pump = selectedPump,
                pairingCode = pairingCode,
                onCodeChanged = onCodeChanged,
                onPair = onPair,
                onCancel = onCancelSelection,
            )
        }

        // Pump selected, show pairing code input
        selectedPump != null -> {
            PairingCodeInput(
                pump = selectedPump,
                pairingCode = pairingCode,
                onCodeChanged = onCodeChanged,
                onPair = onPair,
                onCancel = onCancelSelection,
            )
        }

        // Scan mode
        else -> {
            ScanSection(
                pumps = discoveredPumps,
                isScanning = isScanning,
                onStartScan = onStartScan,
                onStopScan = onStopScan,
                onSelectPump = onSelectPump,
            )
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

private fun requiredAdvertisePermissions(): Array<String> =
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        arrayOf(
            Manifest.permission.BLUETOOTH_ADVERTISE,
            Manifest.permission.BLUETOOTH_CONNECT,
        )
    } else {
        // Pre-Android-12: advertising uses the auto-granted legacy BLUETOOTH/BLUETOOTH_ADMIN
        // install-time permissions. ACCESS_FINE_LOCATION is a *scanning* requirement, not an
        // advertising one, so requesting it here would pop a needless dialog that, if denied, blocks
        // pairing even though advertising would work.
        emptyArray()
    }

/**
 * Advertise-and-wait pairing (phone is the BLE peripheral): the phone advertises as [advertisedName]
 * and the pump connects to it -- there is no scan and no device list. The user triggers pairing from
 * the pump's own menu. States are driven off the connection manager's [connectionState] and [fault]:
 * idle (with the single-peer instruction) -> advertising/waiting -> connecting (SAKE) -> connected
 * (handled by the caller) or failed.
 */
@Composable
private fun AdvertiseAndWaitContent(
    advertisedName: String?,
    isAdvertising: Boolean,
    connectionState: ConnectionState,
    fault: PairingFault?,
    onStartAdvertising: () -> Unit,
    onStopAdvertising: () -> Unit,
) {
    val context = LocalContext.current
    var permissionDenied by remember { mutableStateOf(false) }

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestMultiplePermissions(),
    ) { results ->
        if (results.values.all { it }) {
            permissionDenied = false
            onStartAdvertising()
        } else {
            permissionDenied = true
        }
    }

    fun startWithPermissions() {
        val granted = requiredAdvertisePermissions().all { perm ->
            ContextCompat.checkSelfPermission(context, perm) == PackageManager.PERMISSION_GRANTED
        }
        if (granted) {
            permissionDenied = false
            onStartAdvertising()
        } else {
            permissionLauncher.launch(requiredAdvertisePermissions())
        }
    }

    // The phase is driven off the manager's connection state, not the advertise job's liveness: the
    // scan flow stays open across terminal faults and a completed handshake, so it can't be the source
    // of truth. Only TERMINAL faults route to the idle branch (so they surface their message + Try
    // Again instead of an endless "Waiting" spinner); BOUND_ELSEWHERE means "still advertising, nothing
    // has connected yet", so it stays in the waiting state where the Cancel action is shown.
    val terminalFault = fault != null && fault != PairingFault.BOUND_ELSEWHERE
    when {
        connectionState == ConnectionState.CONNECTING ||
            connectionState == ConnectionState.AUTHENTICATING ->
            ConnectingCard(connectionState)

        connectionState == ConnectionState.SCANNING ||
            (isAdvertising && !terminalFault && connectionState == ConnectionState.DISCONNECTED) ->
            AdvertisingCard(
                advertisedName = advertisedName,
                fault = fault,
                onCancel = onStopAdvertising,
            )

        else -> AdvertiseIdleContent(
            fault = fault,
            permissionDenied = permissionDenied,
            onStart = { startWithPermissions() },
        )
    }
}

@Composable
private fun AdvertiseIdleContent(
    fault: PairingFault?,
    permissionDenied: Boolean,
    onStart: () -> Unit,
) {
    // Single-peer limitation surfaced in the pairing flow (not just the settings card): a pump pairs
    // with one phone at a time, so the official app must release it first.
    Card(
        modifier = Modifier.fillMaxWidth().testTag("single_peer_instruction"),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "Before you start",
                style = MaterialTheme.typography.titleSmall,
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = "A pump pairs with only one phone at a time. If this pump is currently " +
                    "paired with the manufacturer's official app, remove it there first or it " +
                    "will not connect here.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
    Spacer(modifier = Modifier.height(16.dp))

    if (fault != null) {
        FaultCard(fault)
        Spacer(modifier = Modifier.height(8.dp))
    }

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
                    text = "GlycemicGPT needs Bluetooth permissions to make your phone " +
                        "discoverable to the pump. Please grant the permissions when prompted, " +
                        "or enable them in your device settings.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onErrorContainer,
                )
            }
        }
        Spacer(modifier = Modifier.height(8.dp))
    }

    Button(
        onClick = onStart,
        modifier = Modifier.fillMaxWidth().testTag("start_pairing_button"),
    ) {
        Icon(
            imageVector = Icons.Default.Bluetooth,
            contentDescription = null,
            modifier = Modifier.size(20.dp),
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(if (fault != null) "Try Again" else "Start Pairing")
    }
}

@Composable
private fun AdvertisingCard(
    advertisedName: String?,
    fault: PairingFault?,
    onCancel: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth().testTag("advertising_status")) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = "Waiting for your pump",
                    style = MaterialTheme.typography.titleSmall,
                )
            }
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = if (advertisedName != null) {
                    "Your phone is now discoverable as \"$advertisedName\". On your pump, open the " +
                        "pairing menu (Add/Pair new device) and select \"$advertisedName\" to connect."
                } else {
                    "Your phone is now discoverable. On your pump, open the pairing menu and select " +
                        "this phone to connect."
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            // Single-peer fault while waiting is informational, not terminal -- the user can keep
            // waiting or cancel and free the pump from the official app.
            if (fault == PairingFault.BOUND_ELSEWHERE) {
                Spacer(modifier = Modifier.height(12.dp))
                Text(
                    text = faultMessage(fault),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.testTag("pairing_fault"),
                )
            }

            Spacer(modifier = Modifier.height(16.dp))
            OutlinedButton(
                onClick = onCancel,
                modifier = Modifier.fillMaxWidth().testTag("cancel_advertising_button"),
            ) {
                Text("Cancel")
            }
        }
    }
}

@Composable
private fun FaultCard(fault: PairingFault) {
    Card(
        modifier = Modifier.fillMaxWidth().testTag("pairing_fault"),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.errorContainer,
        ),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "Pairing did not complete",
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onErrorContainer,
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = faultMessage(fault),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onErrorContainer,
            )
        }
    }
}

private fun faultMessage(fault: PairingFault): String = when (fault) {
    PairingFault.PERIPHERAL_UNSUPPORTED ->
        "This phone can't act as a Bluetooth accessory, so it can't pair with this pump. " +
            "A different phone may be required."
    PairingFault.ADVERTISE_FAILED ->
        "Couldn't start Bluetooth advertising. Close other Bluetooth apps and try again."
    PairingFault.HANDSHAKE_TIMEOUT ->
        "The pump connected but the secure handshake timed out. Try again."
    PairingFault.AUTH_FAILED ->
        "The pump rejected the secure handshake. Try again."
    PairingFault.BOUND_ELSEWHERE ->
        "No pump has connected yet. If this pump is still paired with the manufacturer's " +
            "official app, remove it there first."
}
