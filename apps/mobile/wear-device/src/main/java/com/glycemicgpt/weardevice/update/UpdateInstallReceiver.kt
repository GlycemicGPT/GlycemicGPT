package com.glycemicgpt.weardevice.update

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import com.glycemicgpt.weardevice.data.WearDataContract
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import timber.log.Timber

/**
 * Receives the result of a PackageInstaller session commit.
 *
 * On success: the app process has already been killed and restarted with the new version,
 * so this receiver typically only fires on failure.
 *
 * On failure: sends a best-effort error status to the phone via MessageClient.
 */
class UpdateInstallReceiver : BroadcastReceiver() {

    companion object {
        const val ACTION_INSTALL_RESULT = "com.glycemicgpt.weardevice.INSTALL_RESULT"
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ACTION_INSTALL_RESULT) {
            Timber.w("Unexpected action: %s", intent.action)
            return
        }
        val status = intent.getIntExtra(
            PackageInstaller.EXTRA_STATUS,
            PackageInstaller.STATUS_FAILURE,
        )
        val message = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)

        when (status) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                // System requires user confirmation -- launch the confirmation activity.
                val confirmIntent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
                } else {
                    @Suppress("DEPRECATION")
                    intent.getParcelableExtra(Intent.EXTRA_INTENT)
                }
                if (confirmIntent != null) {
                    confirmIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    context.startActivity(confirmIntent)
                } else {
                    Timber.w("PENDING_USER_ACTION but no confirmation intent provided")
                }
            }
            PackageInstaller.STATUS_SUCCESS -> {
                // App was replaced -- process killed and restarted. This callback
                // typically won't fire for self-updates since the old process is dead.
                Timber.d("Watch APK install succeeded")
            }
            else -> {
                Timber.w("Watch APK install failed: status=%d message=%s", status, message)
                val pending = goAsync()
                scope.launch {
                    try {
                        sendErrorStatus(context, status, message)
                    } finally {
                        pending.finish()
                    }
                }
            }
        }
    }

    private suspend fun sendErrorStatus(context: Context, status: Int, message: String?) {
        try {
            val messageClient = Wearable.getMessageClient(context)
            val nodeClient = Wearable.getNodeClient(context)
            val nodes = nodeClient.connectedNodes.await()
            val errorMsg = "Install failed: status=$status ${message ?: ""}"
            val payload = "status=error\nerror=${errorMsg.replace('\n', ' ')}\n".toByteArray()

            nodes.forEach { node ->
                messageClient.sendMessage(
                    node.id,
                    WearDataContract.WATCH_APK_PUSH_STATUS_PATH,
                    payload,
                ).await()
            }
        } catch (e: Exception) {
            Timber.w(e, "Failed to send install error status to phone")
        }
    }
}
