package com.glycemicgpt.weardevice.data

import android.content.Context
import com.glycemicgpt.weardevice.BuildConfig
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.tasks.await
import timber.log.Timber

/**
 * Publishes the watch app version info to the Wearable Data Layer so the
 * phone app can check whether a newer APK is available on GitHub Releases.
 */
object WatchVersionPublisher {

    suspend fun publish(context: Context) {
        try {
            val request = PutDataMapRequest.create(WearDataContract.WATCH_VERSION_PATH).apply {
                dataMap.putString(WearDataContract.KEY_WATCH_VERSION_NAME, BuildConfig.VERSION_NAME)
                dataMap.putInt(WearDataContract.KEY_WATCH_VERSION_CODE, BuildConfig.VERSION_CODE)
                dataMap.putString(WearDataContract.KEY_WATCH_UPDATE_CHANNEL, BuildConfig.UPDATE_CHANNEL)
                dataMap.putInt(WearDataContract.KEY_WATCH_DEV_BUILD_NUMBER, BuildConfig.DEV_BUILD_NUMBER)
            }.asPutDataRequest().setUrgent()

            Wearable.getDataClient(context).putDataItem(request).await()
            Timber.d(
                "Published watch version: %s (code=%d, channel=%s, devBuild=%d)",
                BuildConfig.VERSION_NAME,
                BuildConfig.VERSION_CODE,
                BuildConfig.UPDATE_CHANNEL,
                BuildConfig.DEV_BUILD_NUMBER,
            )
        } catch (e: Exception) {
            Timber.w(e, "Failed to publish watch version to DataLayer")
        }
    }
}
