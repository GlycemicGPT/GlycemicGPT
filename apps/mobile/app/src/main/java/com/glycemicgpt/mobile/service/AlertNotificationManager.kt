package com.glycemicgpt.mobile.service

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.glycemicgpt.mobile.data.local.entity.AlertEntity
import com.glycemicgpt.mobile.presentation.MainActivity
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class AlertNotificationManager @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    companion object {
        const val CHANNEL_URGENT = "urgent_alerts"
        const val CHANNEL_STANDARD = "standard_alerts"
        private const val GROUP_KEY = "com.glycemicgpt.ALERTS"
        private const val MAX_NOTIFIED_IDS = 200

        private val LOW_ALERT_TYPES = listOf("low_urgent", "low_warning")
    }

    /** Server IDs we have already shown a notification for. Survives SSE reconnects. */
    private val notifiedServerIds: MutableSet<String> = linkedSetOf()
    private val dedupLock = Any()

    init {
        createChannels()
    }

    private fun createChannels() {
        val manager = context.getSystemService(NotificationManager::class.java)

        val urgentChannel = NotificationChannel(
            CHANNEL_URGENT,
            "Urgent Alerts",
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = "Emergency and urgent glucose alerts"
            setBypassDnd(true)
            enableVibration(true)
        }

        val standardChannel = NotificationChannel(
            CHANNEL_STANDARD,
            "Standard Alerts",
            NotificationManager.IMPORTANCE_DEFAULT,
        ).apply {
            description = "Warning and informational glucose alerts"
        }

        manager.createNotificationChannel(urgentChannel)
        manager.createNotificationChannel(standardChannel)
    }

    /**
     * Returns a stable notification ID for the given alert. Alerts of the same type
     * (and same patient for caregivers) share an ID so Android replaces the previous
     * notification instead of stacking duplicates.
     */
    fun stableNotificationId(alert: AlertEntity): Int {
        val key = "${alert.alertType}|${alert.patientName ?: ""}"
        // Ensure positive and above foreground service IDs (1 = PumpConnection, 2 = AlertStream)
        return (key.hashCode() and 0x7FFFFFFF).coerceAtLeast(100)
    }

    /**
     * Returns true if this is the first notification for this [serverId] (should show).
     * Returns false if we already notified for it (skip to prevent spam on SSE reconnect).
     *
     * Thread-safe: all access to [notifiedServerIds] is synchronized on [dedupLock].
     */
    fun shouldNotify(serverId: String): Boolean = synchronized(dedupLock) {
        val isNew = notifiedServerIds.add(serverId)
        if (isNew && notifiedServerIds.size > MAX_NOTIFIED_IDS) {
            val iterator = notifiedServerIds.iterator()
            repeat(notifiedServerIds.size - MAX_NOTIFIED_IDS) {
                if (iterator.hasNext()) {
                    iterator.next()
                    iterator.remove()
                }
            }
        }
        isNew
    }

    /**
     * Removes a server ID from the dedup set so that future alerts of a new
     * type/instance can trigger a fresh notification.
     */
    fun markAcknowledged(serverId: String): Unit = synchronized(dedupLock) {
        notifiedServerIds.remove(serverId)
    }

    fun showAlertNotification(alert: AlertEntity, notificationId: Int) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(
                    context,
                    Manifest.permission.POST_NOTIFICATIONS,
                ) != PackageManager.PERMISSION_GRANTED
            ) {
                Timber.w("POST_NOTIFICATIONS permission not granted, skipping alert notification")
                return
            }
        }

        val manager = context.getSystemService(NotificationManager::class.java)

        val isLow = alert.alertType in LOW_ALERT_TYPES
        val isUrgent = alert.severity in listOf("urgent", "emergency")
        val channelId = if (isUrgent) CHANNEL_URGENT else CHANNEL_STANDARD

        // Tap notification -> open app to Alerts tab
        val contentIntent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra("navigate_to", "alerts")
        }
        val contentPendingIntent = PendingIntent.getActivity(
            context,
            alert.serverId.hashCode(),
            contentIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        // "Got It" action -> acknowledge without opening the app
        val ackIntent = Intent(context, AlertActionReceiver::class.java).apply {
            action = AlertActionReceiver.ACTION_ACKNOWLEDGE
            putExtra(AlertActionReceiver.EXTRA_SERVER_ID, alert.serverId)
            putExtra(AlertActionReceiver.EXTRA_NOTIFICATION_ID, notificationId)
        }
        // Use a distinct request code from contentPendingIntent to avoid collision
        val ackPendingIntent = PendingIntent.getBroadcast(
            context,
            alert.serverId.hashCode() xor "ack".hashCode(),
            ackIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val title = buildTitle(alert)

        val notification = NotificationCompat.Builder(context, channelId)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle(title)
            .setContentText(alert.message)
            .setStyle(NotificationCompat.BigTextStyle().bigText(alert.message))
            .setPriority(
                if (isUrgent) NotificationCompat.PRIORITY_HIGH
                else NotificationCompat.PRIORITY_DEFAULT,
            )
            .setContentIntent(contentPendingIntent)
            .setAutoCancel(true)
            .setGroup(GROUP_KEY)
            // Lows are life-threatening: re-fire sound on each update.
            // Highs/IoB: alert once, then silent updates only.
            .setOnlyAlertOnce(!isLow)
            .addAction(
                android.R.drawable.ic_menu_close_clear_cancel,
                "Got It",
                ackPendingIntent,
            )
            .build()

        manager.notify(notificationId, notification)
    }

    fun cancelNotification(notificationId: Int) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.cancel(notificationId)
    }

    private fun buildTitle(alert: AlertEntity): String {
        val prefix = when (alert.severity) {
            "emergency" -> "EMERGENCY"
            "urgent" -> "URGENT"
            "warning" -> "Warning"
            else -> "Info"
        }
        val patientSuffix = alert.patientName?.let { " - $it" } ?: ""
        return "$prefix: ${alert.currentValue.toInt()} mg/dL$patientSuffix"
    }
}
