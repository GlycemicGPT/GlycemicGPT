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
import kotlinx.coroutines.Job
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
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
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
        private const val MAX_BACKOFF_MS = 60_000L
        private const val STABLE_CONNECTION_MS = 10_000L // Must be open 10s before resetting backoff
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
    private val reconnectAttempt = AtomicInteger(0)
    private val reconnectScheduled = AtomicBoolean(false)
    private var reconnectJob: Job? = null
    @Volatile
    private var connectionOpenedAtMs = 0L
    /** Generation counter to prevent stale callbacks from racing with new connections. */
    private val connectionGeneration = AtomicInteger(0)

    // Reuse a single OkHttpClient across reconnects to avoid resource leaks
    private val sseClient: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(2, TimeUnit.MINUTES)
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
        reconnectJob?.cancel()
        sseClient.dispatcher.executorService.shutdownNow()
        try {
            sseClient.dispatcher.executorService.awaitTermination(3, TimeUnit.SECONDS)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
        }
        sseClient.connectionPool.evictAll()
        serviceScope.cancel()
        Timber.d("AlertStreamService destroyed")
        super.onDestroy()
    }

    private fun connectToStream() {
        // Cancel any existing connection without triggering another reconnect
        eventSource?.cancel()
        eventSource = null

        val baseUrl = authTokenStore.getBaseUrl() ?: run {
            Timber.w("No base URL configured, cannot connect alert stream")
            return
        }
        val token = authTokenStore.getRawToken() ?: run {
            Timber.w("No auth token available, cannot connect alert stream")
            return
        }

        // Increment generation so stale callbacks from the cancelled EventSource
        // are ignored when they fire after a new connection is established.
        val gen = connectionGeneration.incrementAndGet()
        connectionOpenedAtMs = 0L

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
                    Timber.d("Alert SSE stream connected (status=%d)", response.code)
                    connectionOpenedAtMs = System.currentTimeMillis()
                    // Don't reset reconnectAttempt here -- only reset after
                    // STABLE_CONNECTION_MS to prevent rapid connect/fail cycles
                    // from keeping backoff at 0.
                }

                override fun onEvent(
                    eventSource: EventSource,
                    id: String?,
                    type: String?,
                    data: String,
                ) {
                    // Connection is stable if we're receiving events -- safe to reset backoff
                    resetBackoffIfStable()
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
                    // Ignore callbacks from a stale connection generation
                    if (connectionGeneration.get() != gen) return

                    val code = response?.code
                    val attempt = reconnectAttempt.get()
                    Timber.w(
                        "Alert SSE stream failed (attempt %d, status=%s): %s",
                        attempt, code?.toString() ?: "null", t?.message ?: "unknown",
                    )

                    if (code == 401 || code == 403) {
                        Timber.w("Alert stream auth rejected (HTTP %d), backing off longer", code)
                        reconnectAttempt.set(5.coerceAtLeast(attempt))
                    }

                    scheduleReconnect()
                }

                override fun onClosed(eventSource: EventSource) {
                    if (connectionGeneration.get() != gen) return
                    Timber.d("Alert SSE stream closed by server")
                    scheduleReconnect()
                }
            },
        )
    }

    /** Only reset backoff after the connection has been stable for a while. */
    private fun resetBackoffIfStable() {
        if (connectionOpenedAtMs > 0 &&
            System.currentTimeMillis() - connectionOpenedAtMs >= STABLE_CONNECTION_MS
        ) {
            val prev = reconnectAttempt.getAndSet(0)
            if (prev > 0) {
                Timber.d("Alert stream stable, reset backoff from %d to 0", prev)
            }
        }
    }

    private fun handleAlertEvent(
        data: String,
        adapter: com.squareup.moshi.JsonAdapter<AlertResponse>,
    ) {
        serviceScope.launch {
            try {
                val alertResponse = adapter.fromJson(data) ?: return@launch
                alertRepository.saveAlert(alertResponse)

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
                    if (alertNotificationManager.shouldNotify(alertResponse.id)) {
                        val notifId = alertNotificationManager.stableNotificationId(entity)
                        alertNotificationManager.showAlertNotification(entity, notifId)
                        Timber.d("Alert notified: %s (%s)", alertResponse.id, alertResponse.alertType)
                    } else {
                        Timber.d("Skipping duplicate notification for alert: %s", alertResponse.id)
                    }
                } else {
                    alertNotificationManager.markAcknowledged(alertResponse.id)
                    Timber.d("Alert already acknowledged: %s", alertResponse.id)
                }
            } catch (e: Exception) {
                Timber.e(e, "Failed to process alert event")
            }
        }
    }

    private fun scheduleReconnect() {
        // Prevent multiple concurrent reconnect schedules
        if (!reconnectScheduled.compareAndSet(false, true)) {
            Timber.d("Reconnect already scheduled, skipping")
            return
        }

        val attempt = reconnectAttempt.get()

        val backoffMs = minOf(
            1000L * (1 shl attempt.coerceAtMost(6)),
            MAX_BACKOFF_MS,
        )

        reconnectJob?.cancel()
        reconnectJob = serviceScope.launch {
            try {
                Timber.d("Reconnecting alert stream in %d ms (attempt %d)", backoffMs, attempt)
                delay(backoffMs)

                if (authTokenStore.hasActiveSession()) {
                    connectToStream()
                } else {
                    Timber.d("No active session, stopping alert stream service")
                    stopSelf()
                }
            } finally {
                reconnectScheduled.set(false)
            }
        }

        reconnectAttempt.incrementAndGet()
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
