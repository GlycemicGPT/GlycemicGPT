package com.glycemicgpt.mobile.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.glycemicgpt.mobile.data.repository.AlertRepository
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.DelicateCoroutinesApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.GlobalScope
import kotlinx.coroutines.launch
import timber.log.Timber
import javax.inject.Inject

/**
 * Handles the "Got It" action button on alert notifications.
 *
 * Acknowledges the alert on the backend and dismisses the notification
 * without requiring the user to open the app.
 *
 * Uses [GlobalScope] intentionally: BroadcastReceiver instances are short-lived
 * and may be garbage-collected after [onReceive] returns. The coroutine must
 * outlive the receiver instance, tied only to the [goAsync] pending result.
 */
@AndroidEntryPoint
class AlertActionReceiver : BroadcastReceiver() {

    companion object {
        const val ACTION_ACKNOWLEDGE = "com.glycemicgpt.mobile.ACTION_ACKNOWLEDGE_ALERT"
        const val EXTRA_SERVER_ID = "extra_server_id"
        const val EXTRA_NOTIFICATION_ID = "extra_notification_id"
    }

    @Inject lateinit var alertRepository: AlertRepository
    @Inject lateinit var alertNotificationManager: AlertNotificationManager

    @OptIn(DelicateCoroutinesApi::class)
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ACTION_ACKNOWLEDGE) return

        val serverId = intent.getStringExtra(EXTRA_SERVER_ID) ?: return
        val notificationId = intent.getIntExtra(EXTRA_NOTIFICATION_ID, -1)

        val pendingResult = goAsync()

        GlobalScope.launch(Dispatchers.IO) {
            try {
                alertRepository.acknowledgeAlert(serverId)
                    .onSuccess {
                        Timber.d("Alert acknowledged via notification: %s", serverId)
                        alertNotificationManager.markAcknowledged(serverId)
                        if (notificationId >= 0) {
                            alertNotificationManager.cancelNotification(notificationId)
                        }
                    }
                    .onFailure { e ->
                        Timber.w(e, "Failed to acknowledge alert via notification: %s", serverId)
                    }
            } finally {
                pendingResult.finish()
            }
        }
    }
}
