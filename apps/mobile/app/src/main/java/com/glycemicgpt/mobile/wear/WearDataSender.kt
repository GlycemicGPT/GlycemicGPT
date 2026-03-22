package com.glycemicgpt.mobile.wear

import android.content.Context
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.tasks.await
import org.json.JSONObject
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class WearDataSender @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    private val dataClient by lazy { Wearable.getDataClient(context) }

    suspend fun sendIoB(iob: Float, timestampMs: Long) {
        try {
            val request = PutDataMapRequest.create(WearDataContract.IOB_PATH).apply {
                dataMap.putFloat(WearDataContract.KEY_IOB_VALUE, iob)
                dataMap.putLong(WearDataContract.KEY_IOB_TIMESTAMP, timestampMs)
                // Force delivery even when value is unchanged (DataLayer deduplicates identical data)
                dataMap.putLong("_ts", System.currentTimeMillis())
            }.asPutDataRequest().setUrgent()

            dataClient.putDataItem(request).await()
            Timber.d("Sent IoB to watch: %.2f", iob)
        } catch (e: Exception) {
            Timber.w(e, "Failed to send IoB to watch (no watch connected?)")
        }
    }

    suspend fun sendCgm(
        mgDl: Int,
        trend: String,
        timestampMs: Long,
        low: Int,
        high: Int,
        urgentLow: Int,
        urgentHigh: Int,
    ) {
        try {
            val request = PutDataMapRequest.create(WearDataContract.CGM_PATH).apply {
                dataMap.putInt(WearDataContract.KEY_CGM_MG_DL, mgDl)
                dataMap.putString(WearDataContract.KEY_CGM_TREND, trend)
                dataMap.putLong(WearDataContract.KEY_CGM_TIMESTAMP, timestampMs)
                dataMap.putInt(WearDataContract.KEY_GLUCOSE_LOW, low)
                dataMap.putInt(WearDataContract.KEY_GLUCOSE_HIGH, high)
                dataMap.putInt(WearDataContract.KEY_GLUCOSE_URGENT_LOW, urgentLow)
                dataMap.putInt(WearDataContract.KEY_GLUCOSE_URGENT_HIGH, urgentHigh)
                // Force delivery even when CGM value is unchanged (DataLayer deduplicates identical data)
                dataMap.putLong("_ts", System.currentTimeMillis())
            }.asPutDataRequest().setUrgent()

            dataClient.putDataItem(request).await()
            Timber.d("Sent CGM to watch: %d mg/dL %s", mgDl, trend)
        } catch (e: Exception) {
            Timber.w(e, "Failed to send CGM to watch (no watch connected?)")
        }
    }

    suspend fun sendAlert(type: String, bgValue: Int, timestampMs: Long, message: String) {
        try {
            val request = PutDataMapRequest.create(WearDataContract.ALERT_PATH).apply {
                dataMap.putString(WearDataContract.KEY_ALERT_TYPE, type)
                dataMap.putInt(WearDataContract.KEY_ALERT_BG_VALUE, bgValue)
                dataMap.putLong(WearDataContract.KEY_ALERT_TIMESTAMP, timestampMs)
                dataMap.putString(WearDataContract.KEY_ALERT_MESSAGE, message)
            }.asPutDataRequest().setUrgent()

            dataClient.putDataItem(request).await()
            Timber.d("Sent alert to watch: %s %d mg/dL", type, bgValue)
        } catch (e: Exception) {
            Timber.w(e, "Failed to send alert to watch (no watch connected?)")
        }
    }

    suspend fun clearAlert() {
        sendAlert(type = "none", bgValue = 0, timestampMs = System.currentTimeMillis(), message = "")
    }

    suspend fun sendBasalHistory(data: ByteArray, count: Int) {
        try {
            val request = PutDataMapRequest.create(WearDataContract.BASAL_HISTORY_PATH).apply {
                dataMap.putByteArray(WearDataContract.KEY_HISTORY_DATA, data)
                dataMap.putInt(WearDataContract.KEY_HISTORY_COUNT, count)
                dataMap.putLong("_ts", System.currentTimeMillis())
            }.asPutDataRequest().setUrgent()

            dataClient.putDataItem(request).await()
            Timber.d("Sent basal history to watch: %d records", count)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Timber.w(e, "Failed to send basal history to watch")
        }
    }

    suspend fun sendBolusHistory(data: ByteArray, count: Int) {
        try {
            val request = PutDataMapRequest.create(WearDataContract.BOLUS_HISTORY_PATH).apply {
                dataMap.putByteArray(WearDataContract.KEY_HISTORY_DATA, data)
                dataMap.putInt(WearDataContract.KEY_HISTORY_COUNT, count)
                dataMap.putLong("_ts", System.currentTimeMillis())
            }.asPutDataRequest().setUrgent()

            dataClient.putDataItem(request).await()
            Timber.d("Sent bolus history to watch: %d records", count)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Timber.w(e, "Failed to send bolus history to watch")
        }
    }

    suspend fun sendIoBHistory(data: ByteArray, count: Int) {
        try {
            val request = PutDataMapRequest.create(WearDataContract.IOB_HISTORY_PATH).apply {
                dataMap.putByteArray(WearDataContract.KEY_HISTORY_DATA, data)
                dataMap.putInt(WearDataContract.KEY_HISTORY_COUNT, count)
                dataMap.putLong("_ts", System.currentTimeMillis())
            }.asPutDataRequest().setUrgent()

            dataClient.putDataItem(request).await()
            Timber.d("Sent IoB history to watch: %d records", count)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Timber.w(e, "Failed to send IoB history to watch")
        }
    }

    suspend fun sendCategoryLabels(labels: Map<String, String>) {
        try {
            val json = JSONObject(labels).toString()
            val request = PutDataMapRequest.create(WearDataContract.CATEGORY_LABELS_PATH).apply {
                dataMap.putString(WearDataContract.KEY_CATEGORY_LABELS_JSON, json)
                dataMap.putLong("_ts", System.currentTimeMillis())
            }.asPutDataRequest().setUrgent()

            dataClient.putDataItem(request).await()
            Timber.d("Sent category labels to watch: %d entries", labels.size)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Timber.w(e, "Failed to send category labels to watch")
        }
    }

    suspend fun sendWatchFaceConfig(
        showIoB: Boolean,
        showGraph: Boolean,
        showAlert: Boolean,
        showSeconds: Boolean,
        graphRangeHours: Int,
        theme: String,
        showBasalOverlay: Boolean = true,
        showBolusMarkers: Boolean = true,
        showIoBOverlay: Boolean = true,
        showModeBands: Boolean = true,
        aiTtsEnabled: Boolean = false,
    ) {
        try {
            val request = PutDataMapRequest.create(WearDataContract.CONFIG_PATH).apply {
                dataMap.putBoolean(WearDataContract.KEY_CONFIG_SHOW_IOB, showIoB)
                dataMap.putBoolean(WearDataContract.KEY_CONFIG_SHOW_GRAPH, showGraph)
                dataMap.putBoolean(WearDataContract.KEY_CONFIG_SHOW_ALERT, showAlert)
                dataMap.putBoolean(WearDataContract.KEY_CONFIG_SHOW_SECONDS, showSeconds)
                dataMap.putInt(WearDataContract.KEY_CONFIG_GRAPH_RANGE_HOURS, graphRangeHours)
                dataMap.putString(WearDataContract.KEY_CONFIG_THEME, theme)
                dataMap.putBoolean(WearDataContract.KEY_CONFIG_SHOW_BASAL, showBasalOverlay)
                dataMap.putBoolean(WearDataContract.KEY_CONFIG_SHOW_BOLUS, showBolusMarkers)
                dataMap.putBoolean(WearDataContract.KEY_CONFIG_SHOW_IOB_OVERLAY, showIoBOverlay)
                dataMap.putBoolean(WearDataContract.KEY_CONFIG_SHOW_MODES, showModeBands)
                dataMap.putBoolean(WearDataContract.KEY_CONFIG_AI_TTS, aiTtsEnabled)
                // Timestamp forces DataClient delivery even when config values are unchanged,
                // preventing deduplication from swallowing re-syncs (e.g. on reconnect).
                dataMap.putLong("_ts", System.currentTimeMillis())
            }.asPutDataRequest().setUrgent()

            dataClient.putDataItem(request).await()
            Timber.d("Sent watch face config to watch: theme=%s, graph=%dh", theme, graphRangeHours)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Timber.w(e, "Failed to send watch face config to watch (no watch connected?)")
        }
    }
}
