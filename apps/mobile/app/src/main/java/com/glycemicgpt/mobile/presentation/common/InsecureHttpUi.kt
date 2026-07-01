package com.glycemicgpt.mobile.presentation.common

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.NoEncryption
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp

/**
 * Shared UI for the Story 57.1 insecure-LAN-HTTP opt-in. Both entry points (onboarding server
 * setup and Settings) reuse the same acknowledgement dialog and the same active-mode indicator so
 * the risk framing is identical wherever it appears.
 */

/** Risk copy shown in the acknowledgement dialog; mirrors the onboarding DisclaimerCard tone. */
const val INSECURE_HTTP_RISK_TEXT: String =
    "This lets the app talk to your server over plain http://, which is unencrypted -- anyone on " +
        "the same network could read your data and sign-in token. It is allowed only for " +
        "private/LAN addresses (for example 10.x, 192.168.x, or a .local name); public addresses " +
        "always require https://. Only enable this on a network you trust."

/**
 * "I understand the risk" acknowledgement, modeled on the onboarding DisclaimerCard (warning icon,
 * error tint). Enabling insecure LAN HTTP only happens on [onConfirm].
 */
@Composable
fun InsecureHttpConfirmDialog(
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        icon = {
            Icon(
                imageVector = Icons.Default.Warning,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.error,
            )
        },
        title = { Text("Allow insecure LAN HTTP?") },
        text = { Text(INSECURE_HTTP_RISK_TEXT) },
        confirmButton = {
            TextButton(
                onClick = onConfirm,
                modifier = Modifier.testTag("insecure_http_confirm"),
            ) {
                Text("Enable", color = MaterialTheme.colorScheme.error)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Cancel")
            }
        },
    )
}

/**
 * Persistent indicator shown while insecure-HTTP mode is active (the opt-in is on and the server
 * base URL is `http://`). Mirrors the session-expired banner style with an error tint.
 */
@Composable
fun InsecureHttpBanner(modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.errorContainer)
            .padding(horizontal = 16.dp, vertical = 8.dp)
            .testTag("insecure_http_banner"),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = Icons.Default.NoEncryption,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onErrorContainer,
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(
            text = "Insecure LAN HTTP is on -- traffic to your server is unencrypted.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onErrorContainer,
        )
    }
}
