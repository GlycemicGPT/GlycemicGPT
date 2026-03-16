package com.glycemicgpt.weardevice.push

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.pm.ServiceInfo
import com.glycemicgpt.weardevice.data.WearDataContract
import com.google.android.gms.wearable.ChannelClient
import com.google.android.gms.wearable.Wearable
import com.google.android.gms.wearable.WearableListenerService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.cancel
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.tasks.await
import timber.log.Timber
import java.io.File
import java.io.InputStream
import java.io.OutputStream
import java.util.concurrent.atomic.AtomicInteger

/**
 * Receives watch face APK bytes from the phone app via ChannelClient
 * and installs the watch face using the Watch Face Push API.
 *
 * Flow:
 * 1. Phone opens ChannelClient with path /glycemicgpt/watchface/push
 * 2. Phone streams WFF APK bytes through the channel
 * 3. This service receives channel open, reads bytes to a temp file
 * 4. Calls WatchFacePushManager to install and activate the face
 * 5. Sends status back to phone via MessageClient
 */
class WatchFaceReceiveService : WearableListenerService() {

    companion object {
        /** Max APK size: 50 MB -- WFF faces are typically <5 MB */
        private const val MAX_APK_SIZE_BYTES = 50L * 1024 * 1024
        /** Timeout for receiving APK bytes from phone */
        private const val RECEIVE_TIMEOUT_MS = 120_000L
        /** APK magic bytes (PK zip header) */
        private val APK_MAGIC = byteArrayOf(0x50, 0x4B, 0x03, 0x04)
        private const val NOTIFICATION_CHANNEL_ID = "watchface_push"
        private const val FOREGROUND_ID = 9001
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val installMutex = Mutex()
    private val activePushCount = AtomicInteger(0)
    private val foregroundLock = Any()

    override fun onChannelOpened(channel: ChannelClient.Channel) {
        if (channel.path != WearDataContract.WATCHFACE_PUSH_CHANNEL) return

        Timber.d("Watch face push channel opened from phone")
        synchronized(foregroundLock) {
            if (activePushCount.getAndIncrement() == 0) {
                tryPromoteToForeground()
            }
        }
        scope.launch {
            try {
                installMutex.withLock {
                    receiveAndInstallWatchFace(channel)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // Catches setup failures (e.g. createTempFile on full disk)
                // that occur before receiveAndInstallWatchFace's internal try/finally.
                Timber.e(e, "Watch face push failed before transfer started")
                withContext(NonCancellable) {
                    sendStatus("error", error = e.message ?: "Setup failed")
                    try {
                        Wearable.getChannelClient(applicationContext)
                            .close(channel).await()
                    } catch (ce: Exception) {
                        Timber.w(ce, "Failed to close channel after setup failure")
                    }
                }
            } finally {
                synchronized(foregroundLock) {
                    if (activePushCount.decrementAndGet() == 0) {
                        stopForeground(STOP_FOREGROUND_REMOVE)
                    }
                }
            }
        }
    }

    private fun tryPromoteToForeground() {
        try {
            val nm = getSystemService(NotificationManager::class.java)
            if (nm.getNotificationChannel(NOTIFICATION_CHANNEL_ID) == null) {
                nm.createNotificationChannel(
                    NotificationChannel(
                        NOTIFICATION_CHANNEL_ID,
                        "Watch Face Install",
                        NotificationManager.IMPORTANCE_LOW,
                    ),
                )
            }
            val notification = Notification.Builder(this, NOTIFICATION_CHANNEL_ID)
                .setContentTitle("Installing watch face")
                .setSmallIcon(android.R.drawable.stat_sys_download)
                .setOngoing(true)
                .build()
            startForeground(FOREGROUND_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } catch (e: Exception) {
            Timber.w(e, "Failed to promote to foreground, continuing without protection")
        }
    }

    private suspend fun receiveAndInstallWatchFace(channel: ChannelClient.Channel) {
        // Reject early on unsupported devices to avoid unnecessary transfer and disk I/O
        if (!WatchFaceInstaller.isSupported()) {
            Timber.w("Watch Face Push not supported on this device (API %d)", android.os.Build.VERSION.SDK_INT)
            sendStatus("error", error = "Watch Face Push requires Wear OS 6")
            try {
                Wearable.getChannelClient(this).close(channel).await()
            } catch (e: Exception) {
                Timber.w(e, "Failed to close channel")
            }
            return
        }

        val tempFile = File.createTempFile("watchface-push-", ".apk", cacheDir)
        try {
            // Read APK bytes from channel into temp file with size limit.
            // A watchdog coroutine force-closes the channel if the transfer stalls,
            // since InputStream.read() is a blocking syscall that coroutine cancellation
            // alone cannot interrupt.
            val channelClient = Wearable.getChannelClient(this)
            val inputStream = channelClient.getInputStream(channel).await()
            val watchdog = launchTimeoutWatchdog(channelClient, channel)
            try {
                inputStream.use { input ->
                    tempFile.outputStream().use { output ->
                        copyWithLimit(input, output, MAX_APK_SIZE_BYTES)
                    }
                }
            } finally {
                watchdog.cancel()
            }

            val fileSize = tempFile.length()
            if (fileSize == 0L) {
                Timber.w("Received empty watch face APK, skipping install")
                sendStatus("error", error = "Empty APK received")
                return
            }

            // Validate APK magic bytes (PK zip header)
            if (!hasValidApkHeader(tempFile)) {
                Timber.w("Received file is not a valid APK (bad magic bytes)")
                sendStatus("error", error = "Invalid APK format")
                return
            }

            Timber.d("Received watch face APK: %d bytes", fileSize)

            // Install, send status, and clean up under NonCancellable.
            // The service scope may be cancelled (WearableListenerService.onDestroy)
            // after the channel event is handled but before install + status complete.
            // Use applicationContext since the service context may become stale.
            withContext(NonCancellable) {
                val installer = WatchFaceInstaller(applicationContext)
                val result = installer.installOrUpdate(tempFile)

                when (result) {
                    is WatchFaceInstaller.Result.Installed -> {
                        Timber.d("Watch face installed: slot=%s", result.slotId)
                        sendStatus("installed", slotId = result.slotId)
                    }
                    is WatchFaceInstaller.Result.Updated -> {
                        Timber.d("Watch face updated: slot=%s", result.slotId)
                        sendStatus("updated", slotId = result.slotId)
                    }
                    is WatchFaceInstaller.Result.Error -> {
                        Timber.w("Watch face install failed: %s", result.message)
                        sendStatus("error", error = result.message)
                    }
                }
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Timber.e(e, "Failed to receive/install watch face")
            withContext(NonCancellable) {
                sendStatus("error", error = e.message ?: "Unknown error")
            }
        } finally {
            tempFile.delete()
            withContext(NonCancellable) {
                try {
                    Wearable.getChannelClient(applicationContext)
                        .close(channel).await()
                } catch (e: Exception) {
                    Timber.w(e, "Failed to close channel")
                }
            }
        }
    }

    /**
     * Launch a watchdog that force-closes the channel after [RECEIVE_TIMEOUT_MS].
     * Closing the channel closes the underlying socket, which unblocks any
     * blocking [InputStream.read] call in [copyWithLimit].
     * The caller must cancel the returned [Job] on successful transfer.
     */
    private fun launchTimeoutWatchdog(
        channelClient: ChannelClient,
        channel: ChannelClient.Channel,
    ): Job = scope.launch {
        delay(RECEIVE_TIMEOUT_MS)
        Timber.w("Watch face receive timed out after %d ms, force-closing channel", RECEIVE_TIMEOUT_MS)
        try {
            channelClient.close(channel).await()
        } catch (e: Exception) {
            Timber.w(e, "Failed to force-close channel on timeout")
        }
    }

    /**
     * Copy from input to output with a size limit to prevent disk exhaustion.
     * Throws [IllegalStateException] if the limit is exceeded.
     *
     * The [ensureActive] check between reads provides cooperative cancellation at
     * chunk boundaries (~8KB). For a fully stalled connection, the timeout watchdog
     * force-closes the channel to unblock the blocking [InputStream.read] call.
     */
    private suspend fun copyWithLimit(input: InputStream, output: OutputStream, maxBytes: Long) {
        val buffer = ByteArray(8192)
        var totalBytes = 0L
        var bytesRead: Int
        while (input.read(buffer).also { bytesRead = it } != -1) {
            totalBytes += bytesRead
            currentCoroutineContext().ensureActive()
            if (totalBytes > maxBytes) {
                throw IllegalStateException(
                    "APK exceeds maximum size of ${maxBytes / (1024 * 1024)} MB",
                )
            }
            output.write(buffer, 0, bytesRead)
        }
    }

    /** Validate that the file starts with a PK zip header (APK is a zip file). */
    private fun hasValidApkHeader(file: File): Boolean {
        if (file.length() < APK_MAGIC.size) return false
        val header = ByteArray(APK_MAGIC.size)
        file.inputStream().use { it.read(header) }
        return header.contentEquals(APK_MAGIC)
    }

    /**
     * Send install status back to the phone via MessageClient.
     * Uses a simple `key=value` format with newline separators to avoid
     * delimiter injection (values are sanitized to remove newlines).
     */
    private suspend fun sendStatus(status: String, slotId: String? = null, error: String? = null) {
        try {
            // Use applicationContext: this method may be called from NonCancellable
            // blocks after the service scope is cancelled and onDestroy has run.
            val ctx = applicationContext
            val messageClient = Wearable.getMessageClient(ctx)
            val nodeClient = Wearable.getNodeClient(ctx)
            val nodes = nodeClient.connectedNodes.await()
            val payload = buildString {
                append("status=").appendLine(sanitize(status))
                slotId?.let { append("slot=").appendLine(sanitize(it)) }
                error?.let { append("error=").appendLine(sanitize(it)) }
            }.toByteArray()

            nodes.forEach { node ->
                messageClient.sendMessage(
                    node.id,
                    WearDataContract.WATCHFACE_PUSH_STATUS_PATH,
                    payload,
                ).await()
            }
        } catch (e: Exception) {
            Timber.w(e, "Failed to send push status to phone")
        }
    }

    /** Strip newlines and equals signs from values to prevent payload injection. */
    private fun sanitize(value: String): String =
        value.replace('\n', ' ').replace('\r', ' ').replace('=', '_')

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }
}
