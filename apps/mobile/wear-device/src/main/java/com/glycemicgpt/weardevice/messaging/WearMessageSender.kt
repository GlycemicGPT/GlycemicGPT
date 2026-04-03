package com.glycemicgpt.weardevice.messaging

import android.content.Context
import com.glycemicgpt.weardevice.data.WearDataContract
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.withTimeout
import timber.log.Timber

/**
 * Sends messages from watch to phone via MessageClient.
 * Used for AI chat requests and alert dismiss.
 */
object WearMessageSender {

    private const val WEARABLE_TIMEOUT_MS = 10_000L

    private suspend fun getPhoneNodeId(context: Context): String? {
        return try {
            withTimeout(WEARABLE_TIMEOUT_MS) {
                val capClient = Wearable.getCapabilityClient(context)
                val capInfo = capClient.getCapability(
                    WearDataContract.CHAT_RELAY_CAPABILITY,
                    com.google.android.gms.wearable.CapabilityClient.FILTER_REACHABLE,
                ).await()
                // Prefer capability-matched node; fall back to first connected node
                val capNode = capInfo.nodes.firstOrNull { it.isNearby }
                    ?: capInfo.nodes.firstOrNull()
                if (capNode != null) return@withTimeout capNode.id

                val nodes = Wearable.getNodeClient(context).connectedNodes.await()
                nodes.firstOrNull()?.id
            }
        } catch (e: Exception) {
            Timber.w(e, "Failed to get connected phone node")
            null
        }
    }

    suspend fun sendChatRequest(context: Context, message: String): Boolean {
        val nodeId = getPhoneNodeId(context) ?: run {
            Timber.w("No connected phone found for chat request")
            return false
        }
        return try {
            withTimeout(WEARABLE_TIMEOUT_MS) {
                Wearable.getMessageClient(context)
                    .sendMessage(
                        nodeId,
                        WearDataContract.CHAT_REQUEST_PATH,
                        message.toByteArray(Charsets.UTF_8),
                    )
                    .await()
            }
            Timber.d("Sent chat request to phone (%d chars)", message.length)
            true
        } catch (e: Exception) {
            Timber.w(e, "Failed to send chat request to phone")
            false
        }
    }

    suspend fun sendAlertDismiss(context: Context): Boolean {
        val nodeId = getPhoneNodeId(context) ?: run {
            Timber.w("No connected phone found for alert dismiss")
            return false
        }
        return try {
            withTimeout(WEARABLE_TIMEOUT_MS) {
                Wearable.getMessageClient(context)
                    .sendMessage(
                        nodeId,
                        WearDataContract.ALERT_DISMISS_PATH,
                        ByteArray(0),
                    )
                    .await()
            }
            Timber.d("Sent alert dismiss to phone")
            true
        } catch (e: Exception) {
            Timber.w(e, "Failed to send alert dismiss to phone")
            false
        }
    }
}
