package com.glycemicgpt.mobile.wear

import android.content.Context
import com.google.android.gms.wearable.CapabilityClient
import com.google.android.gms.wearable.ChannelClient
import com.google.android.gms.wearable.Wearable
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.io.File
import java.io.OutputStream
import java.util.concurrent.atomic.AtomicBoolean
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Pushes a downloaded wear APK file to the connected watch via [ChannelClient].
 * The watch-side [WatchApkReceiveService] receives the bytes and installs
 * via PackageInstaller session API.
 *
 * Modeled after [WatchFacePusher] but uses [WearDataContract.WATCH_APK_PUSH_CHANNEL]
 * and streams from a local [File] instead of bundled assets. Uses a longer timeout
 * (300s) since wear APKs are larger than WFF watch faces.
 */
@Singleton
class WearApkPusher @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    sealed class Result {
        data class Success(val status: String) : Result()
        data class Error(val message: String) : Result()
    }

    companion object {
        /** Timeout for the channel send operation (wear APK can be large) */
        private const val SEND_TIMEOUT_MS = 300_000L
    }

    /**
     * Push the [apkFile] to the first connected watch node that advertises
     * the [WearDataContract.WATCH_APP_CAPABILITY].
     */
    suspend fun pushApk(apkFile: File): Result = withContext(Dispatchers.IO) {
        try {
            if (!apkFile.exists() || apkFile.length() == 0L) {
                return@withContext Result.Error("APK file not found or empty")
            }

            val watchNode = findWatchNode()
                ?: return@withContext Result.Error("No watch connected")

            Timber.d(
                "Pushing wear APK to node: %s (%s), size=%d bytes",
                watchNode.displayName,
                watchNode.id,
                apkFile.length(),
            )

            val channelClient = Wearable.getChannelClient(context)
            val channel = channelClient.openChannel(
                watchNode.id,
                WearDataContract.WATCH_APK_PUSH_CHANNEL,
            ).await()

            val channelClosed = AtomicBoolean(false)
            try {
                streamApkToChannel(channelClient, channel, channelClosed, apkFile)
            } finally {
                closeChannelOnce(channelClient, channel, channelClosed)
            }

            Result.Success(status = "sent")
        } catch (e: Exception) {
            Timber.e(e, "Failed to push wear APK")
            Result.Error(e.message ?: "Unknown error")
        }
    }

    private suspend fun findWatchNode(): com.google.android.gms.wearable.Node? {
        return try {
            val capInfo = Wearable.getCapabilityClient(context)
                .getCapability(
                    WearDataContract.WATCH_APP_CAPABILITY,
                    CapabilityClient.FILTER_REACHABLE,
                )
                .await()
            capInfo.nodes.firstOrNull { it.isNearby }
                ?: capInfo.nodes.firstOrNull()
        } catch (e: Exception) {
            Timber.w(e, "CapabilityClient lookup failed, falling back to NodeClient")
            val nodes = Wearable.getNodeClient(context).connectedNodes.await()
            nodes.firstOrNull()
        }
    }

    private suspend fun streamApkToChannel(
        channelClient: ChannelClient,
        channel: ChannelClient.Channel,
        channelClosed: AtomicBoolean,
        apkFile: File,
    ) = coroutineScope {
        val watchdog = launchSendWatchdog(channelClient, channel, channelClosed)
        try {
            val outputStream = channelClient.getOutputStream(channel).await()
            outputStream.use { output ->
                apkFile.inputStream().use { input ->
                    copyToOutput(input, output)
                }
            }
            Timber.d("Wear APK streamed successfully (%d bytes)", apkFile.length())
        } finally {
            watchdog.cancel()
        }
    }

    private fun kotlinx.coroutines.CoroutineScope.launchSendWatchdog(
        channelClient: ChannelClient,
        channel: ChannelClient.Channel,
        channelClosed: AtomicBoolean,
    ): Job = launch {
        delay(SEND_TIMEOUT_MS)
        Timber.w("Wear APK send timed out after %d ms, force-closing channel", SEND_TIMEOUT_MS)
        closeChannelOnce(channelClient, channel, channelClosed)
    }

    private suspend fun closeChannelOnce(
        channelClient: ChannelClient,
        channel: ChannelClient.Channel,
        channelClosed: AtomicBoolean,
    ) {
        if (channelClosed.compareAndSet(false, true)) {
            try {
                channelClient.close(channel).await()
            } catch (e: Exception) {
                Timber.w(e, "Failed to close channel")
            }
        }
    }

    private fun copyToOutput(
        input: java.io.InputStream,
        output: OutputStream,
    ) {
        val buffer = ByteArray(8192)
        var totalBytes = 0L
        var bytesRead: Int
        while (input.read(buffer).also { bytesRead = it } != -1) {
            output.write(buffer, 0, bytesRead)
            totalBytes += bytesRead
        }
        Timber.d("Sent %d bytes to watch", totalBytes)
    }
}
