package com.glycemicgpt.mobile.presentation.settings

import android.Manifest
import android.content.Intent
import android.os.Build
import android.provider.Settings
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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bluetooth
import androidx.compose.material.icons.filled.BluetoothDisabled
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.NotificationsOff
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.filled.Storage
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material.icons.filled.Watch
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import android.content.pm.PackageManager
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import android.widget.Toast
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import java.io.File
import kotlin.math.roundToInt

@Composable
fun SettingsScreen(
    onNavigateToPairing: () -> Unit = {},
    onNavigateToBleDebug: (() -> Unit)? = null,
    settingsViewModel: SettingsViewModel = hiltViewModel(),
) {
    val state by settingsViewModel.uiState.collectAsState()

    // Re-check battery optimization when returning from system settings
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        settingsViewModel.checkBatteryOptimization()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        Text(
            text = "Settings",
            style = MaterialTheme.typography.headlineMedium,
        )

        Spacer(modifier = Modifier.height(16.dp))

        // -- Account Section --
        SectionHeader(title = "Account")
        AccountSection(
            state = state,
            onSaveUrl = settingsViewModel::saveBaseUrl,
            onTestConnection = settingsViewModel::testConnection,
            onLogin = settingsViewModel::login,
            onShowLogout = settingsViewModel::showLogoutConfirm,
            onClearConnectionResult = settingsViewModel::clearConnectionTestResult,
            onClearLoginError = settingsViewModel::clearLoginError,
        )

        Spacer(modifier = Modifier.height(20.dp))

        // -- Pump Section --
        SectionHeader(title = "Pump")
        PumpSection(
            state = state,
            onNavigateToPairing = onNavigateToPairing,
            onShowUnpair = settingsViewModel::showUnpairConfirm,
        )

        // Battery optimization warning (between Pump and Sync)
        if (state.isPumpPaired && state.isBatteryOptimized) {
            Spacer(modifier = Modifier.height(8.dp))
            BatteryOptimizationCard(
                onRequestExemption = settingsViewModel::createBatteryOptimizationIntent,
            )
        }

        Spacer(modifier = Modifier.height(20.dp))

        // -- Sync Section --
        SectionHeader(title = "Sync")
        SyncSection(
            state = state,
            onBackendSyncToggle = settingsViewModel::setBackendSyncEnabled,
            onRetentionChange = settingsViewModel::setDataRetentionDays,
        )

        Spacer(modifier = Modifier.height(20.dp))

        // -- Notifications Section --
        SectionHeader(title = "Notifications")
        NotificationsSection()

        Spacer(modifier = Modifier.height(20.dp))

        // -- Watch Section --
        SectionHeader(title = "Watch")
        WatchSection(
            watchInstalled = state.watchAppInstalled,
            watchConnected = state.watchConnected,
            onCheckStatus = settingsViewModel::checkWatchStatus,
        )

        Spacer(modifier = Modifier.height(20.dp))

        // -- About Section --
        SectionHeader(title = "About")
        AboutSection(
            state = state,
            onCheckForUpdate = settingsViewModel::checkForUpdate,
            onDownloadUpdate = { url, size -> settingsViewModel.downloadAndInstallUpdate(url, size) },
            onGetInstallIntent = settingsViewModel::getInstallIntent,
            onDismissUpdate = settingsViewModel::dismissUpdateState,
        )

        // -- Debug Section (debug builds only) --
        if (onNavigateToBleDebug != null) {
            Spacer(modifier = Modifier.height(20.dp))
            SectionHeader(title = "Developer")
            OutlinedButton(
                onClick = onNavigateToBleDebug,
                modifier = Modifier.fillMaxWidth().testTag("ble_debug_button"),
            ) {
                Text("BLE Debug Console")
            }
        }

        Spacer(modifier = Modifier.height(16.dp))
    }

    // Dialogs
    if (state.showLogoutConfirm) {
        AlertDialog(
            onDismissRequest = settingsViewModel::dismissLogoutConfirm,
            title = { Text("Sign Out") },
            text = { Text("Are you sure you want to sign out? Pump data sync will pause until you sign in again.") },
            confirmButton = {
                TextButton(onClick = settingsViewModel::logout) {
                    Text("Sign Out", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = settingsViewModel::dismissLogoutConfirm) {
                    Text("Cancel")
                }
            },
        )
    }

    if (state.showUnpairConfirm) {
        AlertDialog(
            onDismissRequest = settingsViewModel::dismissUnpairConfirm,
            title = { Text("Unpair Pump") },
            text = { Text("Are you sure you want to unpair this pump? You will need to re-pair to resume data collection.") },
            confirmButton = {
                TextButton(onClick = settingsViewModel::unpair) {
                    Text("Unpair", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = settingsViewModel::dismissUnpairConfirm) {
                    Text("Cancel")
                }
            },
        )
    }
}

@Composable
private fun SectionHeader(title: String) {
    Text(
        text = title,
        style = MaterialTheme.typography.titleMedium,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(bottom = 8.dp),
    )
}

@Composable
private fun NotificationsSection() {
    val context = LocalContext.current

    fun permissionGranted() = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
    } else {
        true // Pre-Android 13: no runtime permission needed
    }
    var isGranted by remember { mutableStateOf(permissionGranted()) }
    // Re-check when returning from system settings
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        isGranted = permissionGranted()
    }

    NotificationStatusCard(
        isGranted = isGranted,
        onEnableClicked = {
            try {
                val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).apply {
                    putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
                }
                context.startActivity(intent)
            } catch (_: android.content.ActivityNotFoundException) {
                Toast.makeText(
                    context,
                    "Please enable notifications for GlycemicGPT in your phone's Settings",
                    Toast.LENGTH_LONG,
                ).show()
            } catch (_: SecurityException) {
                Toast.makeText(
                    context,
                    "Please enable notifications for GlycemicGPT in your phone's Settings",
                    Toast.LENGTH_LONG,
                ).show()
            }
        },
    )
}

@Composable
private fun NotificationStatusCard(
    isGranted: Boolean,
    onEnableClicked: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = if (isGranted) Icons.Default.Notifications else Icons.Default.NotificationsOff,
                    contentDescription = null,
                    tint = if (isGranted) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error,
                    modifier = Modifier.size(24.dp),
                )
                Spacer(modifier = Modifier.width(12.dp))
                Column {
                    Text(
                        text = "Push Notifications",
                        style = MaterialTheme.typography.titleSmall,
                    )
                    Text(
                        text = if (isGranted) "Enabled" else "Disabled -- alerts will not appear on your phone",
                        style = MaterialTheme.typography.bodySmall,
                        color = if (isGranted) {
                            MaterialTheme.colorScheme.primary
                        } else {
                            MaterialTheme.colorScheme.error
                        },
                    )
                }
            }

            if (!isGranted) {
                Spacer(modifier = Modifier.height(12.dp))

                Button(
                    onClick = onEnableClicked,
                    modifier = Modifier
                        .fillMaxWidth()
                        .testTag("enable_notifications_button"),
                ) {
                    Text("Enable Notifications")
                }
            }
        }
    }
}

@Composable
private fun AccountSection(
    state: SettingsUiState,
    onSaveUrl: (String) -> Unit,
    onTestConnection: () -> Unit,
    onLogin: (String, String) -> Unit,
    onShowLogout: () -> Unit,
    onClearConnectionResult: () -> Unit,
    onClearLoginError: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
        ) {
            if (state.isLoggedIn) {
                // Logged-in view: read-only server info + sign out
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = Icons.Default.Storage,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(24.dp),
                    )
                    Spacer(modifier = Modifier.width(12.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = "Connected to",
                            style = MaterialTheme.typography.titleSmall,
                        )
                        if (state.baseUrl.isNotBlank()) {
                            Text(
                                text = state.baseUrl,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                    }
                }

                HorizontalDivider(modifier = Modifier.padding(vertical = 12.dp))

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Column {
                        Text(
                            text = state.userEmail ?: "Signed in",
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(
                                imageVector = Icons.Default.CheckCircle,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.size(14.dp),
                            )
                            Spacer(modifier = Modifier.width(4.dp))
                            Text(
                                text = "Authenticated",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.primary,
                            )
                        }
                    }
                    OutlinedButton(
                        onClick = onShowLogout,
                        colors = ButtonDefaults.outlinedButtonColors(
                            contentColor = MaterialTheme.colorScheme.error,
                        ),
                    ) {
                        Text("Sign Out")
                    }
                }
            } else {
                // Not logged in: full server URL + login form
                var urlInput by remember(state.baseUrl) { mutableStateOf(state.baseUrl) }

                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = Icons.Default.Storage,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(24.dp),
                    )
                    Spacer(modifier = Modifier.width(12.dp))
                    Text(
                        text = "Server Connection",
                        style = MaterialTheme.typography.titleSmall,
                    )
                }

                Spacer(modifier = Modifier.height(12.dp))

                OutlinedTextField(
                    value = urlInput,
                    onValueChange = { urlInput = it },
                    label = { Text("Server URL") },
                    placeholder = { Text("https://your-server.com") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                    modifier = Modifier.fillMaxWidth().testTag("server_url_field"),
                )

                Spacer(modifier = Modifier.height(8.dp))

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    OutlinedButton(
                        onClick = {
                            onSaveUrl(urlInput)
                            onTestConnection()
                        },
                        enabled = !state.isTestingConnection && urlInput.isNotBlank(),
                        modifier = Modifier.weight(1f).testTag("test_connection_button"),
                    ) {
                        if (state.isTestingConnection) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(16.dp),
                                strokeWidth = 2.dp,
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                        }
                        Text(if (state.isTestingConnection) "Testing..." else "Test Connection")
                    }
                }

                state.connectionTestResult?.let { result ->
                    Spacer(modifier = Modifier.height(4.dp))
                    val isSuccess = result.contains("successfully")
                    Text(
                        text = result,
                        style = MaterialTheme.typography.bodySmall,
                        color = if (isSuccess) {
                            MaterialTheme.colorScheme.primary
                        } else {
                            MaterialTheme.colorScheme.error
                        },
                    )
                }

                HorizontalDivider(modifier = Modifier.padding(vertical = 12.dp))

                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = Icons.Default.Person,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(24.dp),
                    )
                    Spacer(modifier = Modifier.width(12.dp))
                    Text(
                        text = "Authentication",
                        style = MaterialTheme.typography.titleSmall,
                    )
                }

                Spacer(modifier = Modifier.height(8.dp))

                var email by remember { mutableStateOf("") }
                var password by remember { mutableStateOf("") }

                OutlinedTextField(
                    value = email,
                    onValueChange = {
                        email = it
                        onClearLoginError()
                    },
                    label = { Text("Email") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                    modifier = Modifier.fillMaxWidth().testTag("email_field"),
                )

                Spacer(modifier = Modifier.height(8.dp))

                OutlinedTextField(
                    value = password,
                    onValueChange = {
                        password = it
                        onClearLoginError()
                    },
                    label = { Text("Password") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    modifier = Modifier.fillMaxWidth().testTag("password_field"),
                )

                state.loginError?.let { error ->
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = error,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }

                Spacer(modifier = Modifier.height(8.dp))

                Button(
                    onClick = { onLogin(email, password) },
                    enabled = !state.isLoggingIn && email.isNotBlank() && password.isNotBlank(),
                    modifier = Modifier.fillMaxWidth().testTag("sign_in_button"),
                ) {
                    if (state.isLoggingIn) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            color = MaterialTheme.colorScheme.onPrimary,
                            strokeWidth = 2.dp,
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                    }
                    Text(if (state.isLoggingIn) "Signing in..." else "Sign In")
                }
            }
        }
    }
}

@Composable
private fun PumpSection(
    state: SettingsUiState,
    onNavigateToPairing: () -> Unit,
    onShowUnpair: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = if (state.isPumpPaired) Icons.Default.Bluetooth else Icons.Default.BluetoothDisabled,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(24.dp),
                )
                Spacer(modifier = Modifier.width(12.dp))
                Column {
                    Text(
                        text = "Tandem t:slim X2",
                        style = MaterialTheme.typography.titleSmall,
                    )
                    Text(
                        text = if (state.isPumpPaired) {
                            "Paired: ${state.pairedPumpAddress}"
                        } else {
                            "Not paired"
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            if (state.isPumpPaired) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    OutlinedButton(
                        onClick = onNavigateToPairing,
                        modifier = Modifier.weight(1f).testTag("repair_button"),
                    ) {
                        Text("Re-pair")
                    }
                    OutlinedButton(
                        onClick = onShowUnpair,
                        colors = ButtonDefaults.outlinedButtonColors(
                            contentColor = MaterialTheme.colorScheme.error,
                        ),
                        modifier = Modifier.weight(1f).testTag("unpair_button"),
                    ) {
                        Text("Unpair")
                    }
                }
            } else {
                Button(
                    onClick = onNavigateToPairing,
                    modifier = Modifier.fillMaxWidth().testTag("pair_pump_button"),
                ) {
                    Text("Pair Pump")
                }
            }
        }
    }
}

@Composable
private fun SyncSection(
    state: SettingsUiState,
    onBackendSyncToggle: (Boolean) -> Unit,
    onRetentionChange: (Int) -> Unit,
) {
    // Backend Sync toggle
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = Icons.Default.Sync,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(24.dp),
                    )
                    Spacer(modifier = Modifier.width(12.dp))
                    Column {
                        Text(
                            text = "Backend Sync",
                            style = MaterialTheme.typography.titleSmall,
                        )
                        Text(
                            text = "Push pump events to GlycemicGPT server",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                Switch(
                    checked = state.backendSyncEnabled,
                    onCheckedChange = onBackendSyncToggle,
                )
            }
        }
    }

    Spacer(modifier = Modifier.height(8.dp))

    // Data Retention
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
        ) {
            var sliderValue by remember(state.dataRetentionDays) {
                mutableStateOf(state.dataRetentionDays.toFloat())
            }

            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = Icons.Default.Schedule,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(24.dp),
                )
                Spacer(modifier = Modifier.width(12.dp))
                Column {
                    Text(
                        text = "Data Retention",
                        style = MaterialTheme.typography.titleSmall,
                    )
                    Text(
                        text = "Keep local data for ${sliderValue.roundToInt()} days",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            Slider(
                value = sliderValue,
                onValueChange = { sliderValue = it },
                onValueChangeFinished = { onRetentionChange(sliderValue.roundToInt()) },
                valueRange = 1f..30f,
                steps = 28,
                modifier = Modifier.fillMaxWidth(),
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    text = "1 day",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = "30 days",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun AboutSection(
    state: SettingsUiState,
    onCheckForUpdate: () -> Unit,
    onDownloadUpdate: (String, Long) -> Unit,
    onGetInstallIntent: (File) -> android.content.Intent,
    onDismissUpdate: () -> Unit,
) {
    val context = LocalContext.current

    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = Icons.Default.Info,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(24.dp),
                )
                Spacer(modifier = Modifier.width(12.dp))
                Text(
                    text = "App Info",
                    style = MaterialTheme.typography.titleSmall,
                )
            }

            Spacer(modifier = Modifier.height(12.dp))

            InfoRow(label = "Version", value = state.appVersion)
            InfoRow(label = "Build", value = state.buildType)
            InfoRow(label = "BLE Protocol", value = "pumpX2 v1.0")

            Spacer(modifier = Modifier.height(8.dp))

            Text(
                text = "Open Source Licenses",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.primary,
            )

            HorizontalDivider(modifier = Modifier.padding(vertical = 12.dp))

            // App Update
            when (val updateState = state.updateState) {
                is UpdateUiState.Idle -> {
                    OutlinedButton(
                        onClick = onCheckForUpdate,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Check for Updates")
                    }
                }

                is UpdateUiState.Checking -> {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center,
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp,
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = "Checking for updates...",
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }

                is UpdateUiState.UpToDate -> {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center,
                    ) {
                        Icon(
                            imageVector = Icons.Default.CheckCircle,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(16.dp),
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = "You are on the latest version",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedButton(
                        onClick = onCheckForUpdate,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Check Again")
                    }
                }

                is UpdateUiState.Available -> {
                    Column {
                        Text(
                            text = "Update available: v${updateState.version}",
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        val sizeMb = updateState.sizeBytes / (1024.0 * 1024.0)
                        Text(
                            text = "Size: ${"%.1f".format(sizeMb)} MB",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        updateState.releaseNotes?.let { notes ->
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = notes,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 3,
                            )
                        }
                        Spacer(modifier = Modifier.height(8.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(
                                onClick = { onDownloadUpdate(updateState.downloadUrl, updateState.sizeBytes) },
                                modifier = Modifier.weight(1f),
                            ) {
                                Text("Download & Install")
                            }
                            OutlinedButton(
                                onClick = onDismissUpdate,
                            ) {
                                Text("Later")
                            }
                        }
                    }
                }

                is UpdateUiState.Downloading -> {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center,
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp,
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = "Downloading update...",
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }

                is UpdateUiState.ReadyToInstall -> {
                    Button(
                        onClick = {
                            val intent = onGetInstallIntent(updateState.apkFile)
                            context.startActivity(intent)
                        },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Install Update")
                    }
                }

                is UpdateUiState.Error -> {
                    Column {
                        Text(
                            text = updateState.message,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        OutlinedButton(
                            onClick = onCheckForUpdate,
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text("Retry")
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun InfoRow(label: String, value: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 2.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun WatchSection(
    watchInstalled: Boolean?,
    watchConnected: Boolean,
    onCheckStatus: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = Icons.Default.Watch,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(24.dp),
                )
                Spacer(modifier = Modifier.width(12.dp))
                Column {
                    Text(
                        text = "Wear OS Companion",
                        style = MaterialTheme.typography.titleSmall,
                    )
                    val statusText = when {
                        watchInstalled == null -> "Status unknown"
                        watchConnected -> "Connected"
                        watchInstalled -> "Installed (not nearby)"
                        else -> "Not installed"
                    }
                    Text(
                        text = statusText,
                        style = MaterialTheme.typography.bodySmall,
                        color = when {
                            watchConnected -> MaterialTheme.colorScheme.primary
                            else -> MaterialTheme.colorScheme.onSurfaceVariant
                        },
                    )
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            if (watchInstalled == true) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = if (watchConnected) Icons.Default.CheckCircle else Icons.Default.Info,
                        contentDescription = null,
                        tint = if (watchConnected) {
                            MaterialTheme.colorScheme.primary
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                        modifier = Modifier.size(16.dp),
                    )
                    Spacer(modifier = Modifier.width(6.dp))
                    Text(
                        text = if (watchConnected) {
                            "Watch face receives BG, IoB, and alerts"
                        } else {
                            "Bring watch nearby to sync data"
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            } else if (watchInstalled == false) {
                Text(
                    text = "Install the GlycemicGPT Wear app on your watch via sideloading. Download the Wear APK from GitHub Releases.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            Spacer(modifier = Modifier.height(8.dp))

            OutlinedButton(
                onClick = onCheckStatus,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("Check Watch Status")
            }
        }
    }
}

@Composable
private fun BatteryOptimizationCard(
    onRequestExemption: () -> android.content.Intent,
) {
    val context = LocalContext.current

    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = Icons.Default.Warning,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.error,
                    modifier = Modifier.size(24.dp),
                )
                Spacer(modifier = Modifier.width(12.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "Battery Optimization Active",
                        style = MaterialTheme.typography.titleSmall,
                    )
                    Text(
                        text = "Android may stop the pump connection when the screen is off. Disable battery optimization for reliable overnight monitoring.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            Button(
                onClick = {
                    try {
                        context.startActivity(onRequestExemption())
                    } catch (_: android.content.ActivityNotFoundException) {
                        Toast.makeText(
                            context,
                            "Please disable battery optimization for GlycemicGPT in your phone's Settings > Battery",
                            Toast.LENGTH_LONG,
                        ).show()
                    }
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .testTag("disable_battery_optimization_button"),
            ) {
                Text("Disable Battery Optimization")
            }
        }
    }
}
