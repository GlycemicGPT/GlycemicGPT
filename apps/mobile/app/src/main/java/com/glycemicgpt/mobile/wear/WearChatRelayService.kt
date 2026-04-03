package com.glycemicgpt.mobile.wear

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.pm.ServiceInfo
import android.os.Build
import androidx.core.app.NotificationCompat
import com.glycemicgpt.mobile.data.repository.AlertRepository
import com.glycemicgpt.mobile.data.repository.ChatRepository
import com.google.android.gms.wearable.MessageEvent
import com.google.android.gms.wearable.Wearable
import com.google.android.gms.wearable.WearableListenerService
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject
import timber.log.Timber
import java.util.concurrent.atomic.AtomicInteger
import javax.inject.Inject

/**
 * Receives chat requests and alert dismiss messages from the watch via
 * Wearable MessageClient.
 *
 * Chat requests require a long-running API call (20-60s for LLM inference).
 * The service promotes itself to foreground with a notification during the
 * API call so Android doesn't destroy it before the response arrives.
 */
@AndroidEntryPoint
class WearChatRelayService : WearableListenerService() {

    @Inject lateinit var chatRepository: ChatRepository
    @Inject lateinit var alertRepository: AlertRepository
    @Inject lateinit var wearDataSender: WearDataSender

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /** Tracks active foreground work items. Only stop foreground when count hits 0. */
    private val activeWorkCount = AtomicInteger(0)

    override fun onMessageReceived(messageEvent: MessageEvent) {
        when (messageEvent.path) {
            WearDataContract.CHAT_REQUEST_PATH -> handleChatRequest(messageEvent)
            WearDataContract.ALERT_DISMISS_PATH -> handleAlertDismiss()
            else -> super.onMessageReceived(messageEvent)
        }
    }

    private fun handleAlertDismiss() {
        Timber.d("Received alert dismiss from watch")
        startWork()
        try {
            runBlocking {
                val serverId = alertRepository.getLatestUnacknowledgedServerId()
                if (serverId != null) {
                    alertRepository.acknowledgeAlert(serverId)
                    Timber.d("Acknowledged alert %s from watch dismiss", serverId)
                }
                wearDataSender.clearAlert()
            }
        } catch (e: Exception) {
            Timber.w(e, "Failed to acknowledge alert on phone side")
        } finally {
            finishWork()
        }
    }

    @Suppress("TooGenericExceptionCaught")
    private fun handleChatRequest(messageEvent: MessageEvent) {
        val requestText = messageEvent.data?.let { String(it, Charsets.UTF_8).trim() } ?: ""
        val sourceNodeId = messageEvent.sourceNodeId

        if (requestText.isEmpty()) {
            Timber.w("Empty chat request received, ignoring")
            serviceScope.launch { sendError(sourceNodeId, "Empty message") }
            return
        }

        if (requestText.length > MAX_MESSAGE_LENGTH) {
            Timber.w("Chat request too long (%d chars), rejecting", requestText.length)
            serviceScope.launch { sendError(sourceNodeId, "Message too long (max $MAX_MESSAGE_LENGTH chars)") }
            return
        }

        Timber.d("Received chat request from watch (%d chars)", requestText.length)

        // Promote to foreground so Android doesn't kill the process during the
        // long-running LLM API call (20-60s). Then block the binder thread so
        // GMS doesn't unbind the WearableListenerService before the response
        // arrives. onMessageReceived runs on a background binder thread (not
        // main), so blocking won't cause ANR.
        startWork()
        try {
            runBlocking {
                val result = withTimeoutOrNull(CHAT_API_TIMEOUT_MS) {
                    chatRepository.sendMessage(requestText)
                }

                if (result == null) {
                    Timber.w("Chat API call timed out after %dms", CHAT_API_TIMEOUT_MS)
                    sendError(sourceNodeId, "Request timed out. Try again later.")
                    return@runBlocking
                }

                result
                    .onSuccess { chatResponse ->
                        val responseJson = JSONObject().apply {
                            put("response", chatResponse.response)
                            put("disclaimer", chatResponse.disclaimer)
                        }.toString()

                        try {
                            Wearable.getMessageClient(this@WearChatRelayService)
                                .sendMessage(
                                    sourceNodeId,
                                    WearDataContract.CHAT_RESPONSE_PATH,
                                    responseJson.toByteArray(Charsets.UTF_8),
                                )
                                .await()
                            Timber.d("Sent chat response to watch")
                        } catch (e: CancellationException) {
                            throw e
                        } catch (e: Exception) {
                            Timber.w(e, "Failed to send chat response to watch")
                        }
                    }
                    .onFailure { error ->
                        Timber.w(error, "Chat request failed")
                        sendError(sourceNodeId, sanitizeErrorMessage(error))
                    }
            }
        } catch (e: Exception) {
            Timber.e(e, "Chat relay exception: %s", e.message)
        } finally {
            finishWork()
        }
    }

    // --- Foreground service lifecycle ---

    /**
     * Promote to foreground before starting long-running work.
     * Uses an atomic counter so concurrent work items (e.g., chat + alert dismiss
     * arriving simultaneously) keep the foreground state until ALL complete.
     */
    private fun startWork() {
        if (activeWorkCount.getAndIncrement() == 0) {
            ensureNotificationChannel()
            val notification = buildNotification()
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
            } else {
                startForeground(NOTIFICATION_ID, notification)
            }
            Timber.d("Chat relay promoted to foreground")
        }
    }

    /** Demote from foreground when all work items complete. */
    private fun finishWork() {
        if (activeWorkCount.decrementAndGet() <= 0) {
            activeWorkCount.set(0) // clamp to 0
            stopForeground(STOP_FOREGROUND_REMOVE)
            Timber.d("Chat relay returned to background")
        }
    }

    private fun ensureNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Watch Chat Relay",
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = "Processing AI chat request from watch"
            setShowBadge(false)
        }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun buildNotification(): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Processing watch request")
            .setContentText("Asking AI...")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setOngoing(true)
            .setSilent(true)
            .build()
    }

    // --- Error handling ---

    private fun sanitizeErrorMessage(error: Throwable): String {
        val raw = error.message ?: "Unknown error"
        return when {
            raw.contains("timeout", ignoreCase = true) -> "Request timed out. Try again later."
            raw.contains("Unable to resolve host", ignoreCase = true) -> "No internet connection."
            raw.contains("401", ignoreCase = true) -> "Session expired. Open phone app to sign in."
            raw.contains("500", ignoreCase = true) -> "Server error. Try again later."
            else -> "Something went wrong. Try again later."
        }
    }

    private suspend fun sendError(nodeId: String, message: String) {
        try {
            Wearable.getMessageClient(this@WearChatRelayService)
                .sendMessage(
                    nodeId,
                    WearDataContract.CHAT_ERROR_PATH,
                    message.toByteArray(Charsets.UTF_8),
                )
                .await()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Timber.w(e, "Failed to send error to watch")
        }
    }

    override fun onDestroy() {
        serviceScope.cancel()
        super.onDestroy()
    }

    companion object {
        const val MAX_MESSAGE_LENGTH = 500
        private const val CHAT_API_TIMEOUT_MS = 90_000L
        private const val CHANNEL_ID = "watch_chat_relay"
        private const val NOTIFICATION_ID = 3
    }
}
