package com.glycemicgpt.mobile.presentation.alerts

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.glycemicgpt.mobile.data.network.NetworkStatus
import com.glycemicgpt.mobile.service.AlertStreamState

/** testTag for the honest "server alerts paused" banner. */
const val TAG_ALERTING_DEGRADED_BANNER = "alerting_degraded_banner"

/**
 * Whether server-pushed alerting is degraded: the alert SSE stream is not connected, or we can't
 * reach the backend at all. Either way no new server alerts arrive, and the UI must say so.
 *
 * Pure so the visibility rule is unit-testable. Deliberately pessimistic on disagreement between
 * the two signals — the SSE read timeout is minutes long, so [NetworkStatus] usually notices an
 * outage first; conversely a stream stuck reconnecting is degraded even while HTTP still works.
 */
fun isAlertingDegraded(networkStatus: NetworkStatus, streamState: AlertStreamState): Boolean =
    networkStatus != NetworkStatus.REACHABLE || streamState != AlertStreamState.CONNECTED

/**
 * The honest alerting-degraded banner: server-pushed alerts are paused and no new alerts will
 * arrive until reconnected. It must NOT claim any device/local alert floor — none exists yet, and
 * implying one would give a false sense of safety. Cached past alerts remain visible below it.
 */
@Composable
fun AlertingDegradedBanner(modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .testTag(TAG_ALERTING_DEGRADED_BANNER),
        color = MaterialTheme.colorScheme.errorContainer,
        shape = RoundedCornerShape(8.dp),
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = Icons.Default.CloudOff,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onErrorContainer,
                modifier = Modifier.size(20.dp),
            )
            Spacer(Modifier.width(12.dp))
            Text(
                text = "Server alerts paused — no new alerts will arrive until the connection " +
                    "is restored. Alerts below are from before the disconnect.",
                style = MaterialTheme.typography.bodySmall,
                fontWeight = FontWeight.Medium,
                color = MaterialTheme.colorScheme.onErrorContainer,
            )
        }
    }
}
