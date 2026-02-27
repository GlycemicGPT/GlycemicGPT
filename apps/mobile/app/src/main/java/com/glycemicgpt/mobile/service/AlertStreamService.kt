package com.glycemicgpt.mobile.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.glycemicgpt.mobile.data.local.AuthTokenStore
import com.glycemicgpt.mobile.data.local.entity.AlertEntity
import com.glycemicgpt.mobile.data.remote.dto.AlertResponse
import com.glycemicgpt.mobile.data.repository.AlertRepository
import com.squareup.moshi.Moshi
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import timber.log.Timber
import java.time.Instant
import java.util.concurrent.TimeUnit
import javax.inject.Inject

/**
 * Foreground service that maintains a persistent SSE connection to the backend
 * for receiving real-time glucose alert notifications.
 */
@AndroidEntryPoint
class AlertStreamService : Service() {

    companion object {
        const val CHANNEL_ID = "alert_stream"
        const val NOTIFICATION_ID = 2

        fun start(context: Context) {
            context.startForegroundService(Intent(context, AlertStreamService::class.java))
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, AlertStreamService::class.java))
        }
    }

    @Inject lateinit var authTokenStore: AuthTokenStore
    @Inject lateinit var alertRepository: AlertRepository
    @Inject lateinit var alertNotificationManager: AlertNotificationManager
    @Inject lateinit var moshi: Moshi

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var eventSource: EventSource? = null
    private var reconnectAttempt = 0
    private val maxBackoffMs = 60_000L

    // Reuse a single OkHttpClient across reconnects to avoid resource leaks
    private val sseClient: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.SECONDS) // No timeout for SSE
            .build()
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        Timber.d("AlertStreamService created")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(NOTIFICATION_ID, buildNotification())
        connectToStream()
        Timber.d("AlertStreamService started")
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        eventSource?.cancel()
        serviceScope.cancel()
        sseClient.dispatcher.executorService.shutdown()
        sseClient.connectionPool.evictAll()
        Timber.d("AlertStreamService destroyed")
        super.onDestroy()
    }

    private fun connectToStream() {
        // Cancel any existing connection first
        eventSource?.cancel()

        val baseUrl = authTokenStore.getBaseUrl() ?: return
        // Use getRawToken() to avoid early-return when the access token is merely
        // expired.  The SSE client has no TokenRefreshInterceptor, so an expired
        // token will produce a 401 → onFailure → scheduleReconnect.  By that time
        // AuthManager should have refreshed the token in the background.
        val token = authTokenStore.getRawToken() ?: return

        val request = Request.Builder()
            .url("$baseUrl/api/v1/alerts/stream")
            .addHeader("Authorization", "Bearer $token")
            .addHeader("Accept", "text/event-stream")
            .build()

        val adapter = moshi.adapter(AlertResponse::class.java)

        eventSource = EventSources.createFactory(sseClient).newEventSource(
            request,
            object : EventSourceListener() {
                override fun onOpen(eventSource: EventSource, response: Response) {
                    Timber.d("Alert SSE stream connected")
                    reconnectAttempt = 0
                }

                override fun onEvent(
                    eventSource: EventSource,
                    id: String?,
                    type: String?,
                    data: String,
                ) {
                    when (type) {
                        "alert" -> handleAlertEvent(data, adapter)
                        "heartbeat" -> Timber.v("Alert SSE heartbeat")
                    }
                }

                override fun onFailure(
                    eventSource: EventSource,
                    t: Throwable?,
                    response: Response?,
                ) {
                    Timber.w(t, "Alert SSE stream failed (attempt %d)", reconnectAttempt)
                    scheduleReconnect()
                }

                override fun onClosed(eventSource: EventSource) {
                    Timber.d("Alert SSE stream closed")
                    scheduleReconnect()
                }
            },
        )
    }

    private fun handleAlertEvent(
        data: String,
        adapter: com.squareup.moshi.JsonAdapter<AlertResponse>,
    ) {
        serviceScope.launch {
            try {
                val alertResponse = adapter.fromJson(data) ?: return@launch
                // saveAlert inserts to Room (REPLACE on conflict)
                alertRepository.saveAlert(alertResponse)

                // Build entity for notification display from the same parsed data
                val timestampMs = try {
                    Instant.parse(alertResponse.timestamp).toEpochMilli()
                } catch (e: Exception) {
                    System.currentTimeMillis()
                }

                if (!alertResponse.acknowledged) {
                    val entity = AlertEntity(
                        serverId = alertResponse.id,
                        alertType = alertResponse.alertType,
                        severity = alertResponse.severity,
                        message = alertResponse.message,
                        currentValue = alertResponse.currentValue,
                        predictedValue = alertResponse.predictedValue,
                        iobValue = alertResponse.iobValue,
                        trendRate = alertResponse.trendRate,
                        patientName = alertResponse.patientName,
                        acknowledged = alertResponse.acknowledged,
                        timestampMs = timestampMs,
                    )
                    // Only show notification if we haven't already notified for this alert.
                    // Prevents spam on SSE reconnects which resend all unacknowledged alerts.
                    if (alertNotificationManager.shouldNotify(alertResponse.id)) {
                        val notifId = alertNotificationManager.stableNotificationId(entity)
                        alertNotificationManager.showAlertNotification(entity, notifId)
                        Timber.d("Alert notified: %s (%s)", alertResponse.id, alertResponse.alertType)
                    } else {
                        Timber.d("Skipping duplicate notification for alert: %s", alertResponse.id)
                    }
                } else {
                    // Alert was acknowledged server-side; clear from dedup set
                    alertNotificationManager.markAcknowledged(alertResponse.id)
                    Timber.d("Alert already acknowledged: %s", alertResponse.id)
                }
            } catch (e: Exception) {
                Timber.e(e, "Failed to process alert event")
            }
        }
    }

    private fun scheduleReconnect() {
        val backoffMs = minOf(
            (1000L * (1 shl reconnectAttempt.coerceAtMost(6))),
            maxBackoffMs,
        )
        reconnectAttempt++

        serviceScope.launch {
            Timber.d("Reconnecting alert stream in %d ms", backoffMs)
            delay(backoffMs)
            if (authTokenStore.hasActiveSession()) {
                connectToStream()
            } else {
                Timber.d("No active session, stopping alert stream service")
                stopSelf()
            }
        }
    }

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Alert Monitoring",
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = "Monitors for glucose alerts from the server"
            setShowBadge(false)
        }
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(channel)
    }

    private fun buildNotification(): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("GlycemicGPT Alert Monitor")
            .setContentText("Listening for glucose alerts")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setOngoing(true)
            .setSilent(true)
            .build()
    }
}
