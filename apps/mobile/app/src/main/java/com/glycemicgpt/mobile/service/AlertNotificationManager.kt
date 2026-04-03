package com.glycemicgpt.mobile.service

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.RingtoneManager
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.glycemicgpt.mobile.data.local.AlertSoundCategory
import com.glycemicgpt.mobile.data.local.AlertSoundStore
import com.glycemicgpt.mobile.data.local.entity.AlertEntity
import com.glycemicgpt.mobile.presentation.MainActivity
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class AlertNotificationManager @Inject constructor(
    @ApplicationContext private val context: Context,
    private val alertSoundStore: AlertSoundStore,
) {
    companion object {
        private const val GROUP_KEY = "com.glycemicgpt.ALERTS"
        private const val MAX_NOTIFIED_IDS = 200

        private val LOW_ALERT_TYPES = listOf("low_urgent", "low_warning")
        private val HIGH_ALERT_TYPES = listOf("high_warning", "high_urgent")

        // Legacy channel IDs to clean up on migration
        private val LEGACY_CHANNEL_IDS = listOf(
            "urgent_alerts",
            "standard_alerts",
            "urgent_alerts_v2",
            "standard_alerts_v2",
        )

        private const val KEY_SAVED_ALARM_VOLUME = "saved_alarm_volume"

        fun lowChannelId(version: Int) = "low_alerts_v$version"
        fun highChannelId(version: Int) = "high_alerts_v$version"
        fun aiChannelId(version: Int) = "ai_notifications_v$version"
    }

    private val manager = context.getSystemService(NotificationManager::class.java)

    /** Server IDs we have already shown a notification for. Survives SSE reconnects. */
    private val notifiedServerIds: MutableSet<String> = linkedSetOf()
    private val dedupLock = Any()

    /** SharedPreferences key for persisting saved alarm volume across process restarts. */
    private val volumePrefs = context.getSharedPreferences("alert_volume", Context.MODE_PRIVATE)

    /** Alarm volume before we boosted it, or -1 if no boost is active. Thread-safe via prefs. */
    private var savedAlarmVolume: Int
        get() = volumePrefs.getInt(KEY_SAVED_ALARM_VOLUME, -1)
        set(value) { volumePrefs.edit().putInt(KEY_SAVED_ALARM_VOLUME, value).apply() }

    init {
        deleteLegacyChannels()
        createChannels()
        // Restore alarm volume if it was boosted before a process restart
        restoreAlarmVolume()
    }

    private fun deleteLegacyChannels() {
        for (id in LEGACY_CHANNEL_IDS) {
            manager.deleteNotificationChannel(id)
        }
    }

    private fun createChannels() {
        createLowChannel(
            alertSoundStore.lowChannelVersion,
            parseSoundUri(alertSoundStore.lowAlertSoundUri),
        )
        createHighChannel(
            alertSoundStore.highChannelVersion,
            parseSoundUri(alertSoundStore.highAlertSoundUri),
        )
        createAiChannel(
            alertSoundStore.aiChannelVersion,
            parseSoundUri(alertSoundStore.aiNotificationSoundUri),
            silent = isSilent(alertSoundStore.aiNotificationSoundUri),
        )
    }

    /**
     * Parses a stored sound URI string. Returns `null` for both unset (`null`)
     * and explicitly silent ([AlertSoundStore.SILENT_URI]) -- the caller
     * distinguishes them via the [isSilent] flag on the channel creation method.
     */
    private fun parseSoundUri(stored: String?): Uri? = when (stored) {
        null, AlertSoundStore.SILENT_URI -> null
        else -> Uri.parse(stored)
    }

    /** Returns true if the stored URI represents explicit silence. */
    private fun isSilent(stored: String?): Boolean = stored == AlertSoundStore.SILENT_URI

    private fun createLowChannel(version: Int, soundUri: Uri?) {
        val channelId = lowChannelId(version)
        val channel = NotificationChannel(
            channelId,
            "Low Glucose Alerts",
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = "Life-threatening low glucose alerts"
            setBypassDnd(true)
            enableVibration(true)
            vibrationPattern = longArrayOf(0, 500, 200, 500, 200, 500)
            setSound(
                soundUri ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM),
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ALARM)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build(),
            )
        }
        manager.createNotificationChannel(channel)
    }

    private fun createHighChannel(version: Int, soundUri: Uri?) {
        val channelId = highChannelId(version)
        val channel = NotificationChannel(
            channelId,
            "High Glucose Alerts",
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = "High glucose and insulin alerts"
            setBypassDnd(true)
            enableVibration(true)
            setSound(
                soundUri ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION),
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_NOTIFICATION_EVENT)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build(),
            )
        }
        manager.createNotificationChannel(channel)
    }

    private fun createAiChannel(version: Int, soundUri: Uri?, silent: Boolean = false) {
        val channelId = aiChannelId(version)
        val channel = NotificationChannel(
            channelId,
            "AI Notifications",
            NotificationManager.IMPORTANCE_DEFAULT,
        ).apply {
            description = "AI analysis insights and daily briefs"
            if (silent) {
                setSound(null, null)
            } else {
                setSound(
                    soundUri ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION),
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_NOTIFICATION)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build(),
                )
            }
        }
        manager.createNotificationChannel(channel)
    }

    /** Lock to prevent channel recreation racing with notification posting. */
    private val channelLock = Any()

    /**
     * Deletes the old versioned channel and creates a new one with the
     * next version number and the current sound URI from [AlertSoundStore].
     */
    fun recreateChannel(category: AlertSoundCategory) = synchronized(channelLock) {
        val oldVersion = alertSoundStore.getChannelVersion(category)
        val oldChannelId = when (category) {
            AlertSoundCategory.LOW_ALERT -> lowChannelId(oldVersion)
            AlertSoundCategory.HIGH_ALERT -> highChannelId(oldVersion)
            AlertSoundCategory.AI_NOTIFICATION -> aiChannelId(oldVersion)
        }
        manager.deleteNotificationChannel(oldChannelId)

        val newVersion = alertSoundStore.incrementChannelVersion(category)
        val storedUri = alertSoundStore.getSoundUri(category)
        val soundUri = parseSoundUri(storedUri)

        when (category) {
            AlertSoundCategory.LOW_ALERT -> createLowChannel(newVersion, soundUri)
            AlertSoundCategory.HIGH_ALERT -> createHighChannel(newVersion, soundUri)
            AlertSoundCategory.AI_NOTIFICATION -> createAiChannel(newVersion, soundUri, silent = isSilent(storedUri))
        }
        Timber.d("Recreated channel %s -> v%d", category.name, newVersion)
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

        val isLow = alert.alertType in LOW_ALERT_TYPES

        // Supplementary volume boost for low alerts (like FreeStyle Libre)
        if (isLow && alertSoundStore.overrideSilentForLowAlerts) {
            boostAlarmVolume()
        }

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
        val isUrgent = alert.severity in listOf("urgent", "emergency")

        // Resolve channel ID and post notification under channelLock so that
        // recreateChannel() cannot delete the channel between resolve and notify.
        synchronized(channelLock) {
            val channelId = resolveChannelIdLocked(alert)
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
    }

    fun cancelNotification(notificationId: Int) {
        manager.cancel(notificationId)
    }

    /**
     * Restores alarm volume to the level saved before [boostAlarmVolume] was called.
     * Called from [AlertActionReceiver] when the user acknowledges a low alert.
     */
    fun restoreAlarmVolume() {
        val saved = savedAlarmVolume
        if (saved < 0) return
        try {
            val audioManager = context.getSystemService(AudioManager::class.java)
            audioManager.setStreamVolume(AudioManager.STREAM_ALARM, saved, 0)
            savedAlarmVolume = -1 // Only clear after successful restore
            Timber.d("Restored alarm volume to %d", saved)
        } catch (e: Exception) {
            Timber.w(e, "Cannot restore alarm volume to %d; will retry", saved)
        }
    }

    internal fun resolveChannelId(alert: AlertEntity): String = synchronized(channelLock) {
        resolveChannelIdLocked(alert)
    }

    /** Must be called while holding [channelLock]. */
    private fun resolveChannelIdLocked(alert: AlertEntity): String {
        val isLow = alert.alertType in LOW_ALERT_TYPES
        val isHigh = alert.alertType in HIGH_ALERT_TYPES
        return when {
            isLow -> lowChannelId(alertSoundStore.lowChannelVersion)
            isHigh -> highChannelId(alertSoundStore.highChannelVersion)
            else -> aiChannelId(alertSoundStore.aiChannelVersion)
        }
    }

    private fun boostAlarmVolume() {
        try {
            val audioManager = context.getSystemService(AudioManager::class.java)
            val current = audioManager.getStreamVolume(AudioManager.STREAM_ALARM)
            val max = audioManager.getStreamMaxVolume(AudioManager.STREAM_ALARM)
            if (current < max) {
                savedAlarmVolume = current
                audioManager.setStreamVolume(AudioManager.STREAM_ALARM, max, 0)
                Timber.d("Boosted alarm volume from %d to %d", current, max)
            }
        } catch (e: Exception) {
            Timber.w(e, "Cannot modify alarm volume")
        }
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
