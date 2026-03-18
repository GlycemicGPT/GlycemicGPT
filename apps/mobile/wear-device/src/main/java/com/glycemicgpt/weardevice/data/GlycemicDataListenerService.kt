package com.glycemicgpt.weardevice.data

import android.content.ComponentName
import android.os.VibrationEffect
import android.os.VibratorManager
import androidx.wear.watchface.complications.datasource.ComplicationDataSourceUpdateRequester
import com.glycemicgpt.weardevice.complications.BgComplicationDataSource
import com.glycemicgpt.weardevice.complications.GraphComplicationDataSource
import com.glycemicgpt.weardevice.complications.IoBComplicationDataSource
import com.glycemicgpt.weardevice.util.GlucoseDisplayUtils
import com.glycemicgpt.weardevice.util.GlucoseDisplayUtils.sanitizeThresholds
import com.google.android.gms.wearable.DataEvent
import com.google.android.gms.wearable.DataEventBuffer
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.MessageEvent
import com.google.android.gms.wearable.WearableListenerService
import org.json.JSONObject
import timber.log.Timber

class GlycemicDataListenerService : WearableListenerService() {

    override fun onDataChanged(dataEvents: DataEventBuffer) {
        var iobUpdated = false
        var cgmUpdated = false
        var configUpdated = false

        // Two-pass processing: config events first so that data/alert events
        // see the latest showAlert / showIoB state within the same batch.
        val changedEvents = dataEvents.filter { it.type == DataEvent.TYPE_CHANGED }

        // Pass 1 -- config
        changedEvents.forEach { event ->
            val path = event.dataItem.uri.path ?: return@forEach
            if (path != WearDataContract.CONFIG_PATH) return@forEach
            val dataMap = DataMapItem.fromDataItem(event.dataItem).dataMap

            WatchDataRepository.updateWatchFaceConfig(
                showIoB = dataMap.getBoolean(WearDataContract.KEY_CONFIG_SHOW_IOB, true),
                showGraph = dataMap.getBoolean(WearDataContract.KEY_CONFIG_SHOW_GRAPH, true),
                showAlert = dataMap.getBoolean(WearDataContract.KEY_CONFIG_SHOW_ALERT, true),
                showSeconds = dataMap.getBoolean(WearDataContract.KEY_CONFIG_SHOW_SECONDS, false),
                graphRangeHours = dataMap.getInt(WearDataContract.KEY_CONFIG_GRAPH_RANGE_HOURS, 3),
                theme = dataMap.getString(WearDataContract.KEY_CONFIG_THEME, "dark"),
                showBasalOverlay = dataMap.getBoolean(WearDataContract.KEY_CONFIG_SHOW_BASAL, true),
                showBolusMarkers = dataMap.getBoolean(WearDataContract.KEY_CONFIG_SHOW_BOLUS, true),
                showIoBOverlay = dataMap.getBoolean(WearDataContract.KEY_CONFIG_SHOW_IOB_OVERLAY, true),
                showModeBands = dataMap.getBoolean(WearDataContract.KEY_CONFIG_SHOW_MODES, true),
            )
            configUpdated = true
            Timber.d("Received watch face config from phone")
        }

        // Pass 2 -- data, alert, and history events
        var historyUpdated = false
        changedEvents.forEach { event ->
            val path = event.dataItem.uri.path ?: return@forEach
            val dataMap = DataMapItem.fromDataItem(event.dataItem).dataMap

            when (path) {
                WearDataContract.BASAL_HISTORY_PATH -> {
                    val data = dataMap.getByteArray(WearDataContract.KEY_HISTORY_DATA)
                    val count = dataMap.getInt(WearDataContract.KEY_HISTORY_COUNT, 0)
                    if (data != null && count > 0 && count <= MAX_HISTORY_RECORDS) {
                        val records = WearHistorySerializer.decodeBasalHistory(data, count)
                        WatchDataRepository.updateBasalHistory(
                            records.filter { it.timestampMs > 0 && it.rate >= 0f }
                                .map {
                                    WatchDataRepository.BasalHistoryRecord(
                                        rate = it.rate,
                                        timestampMs = it.timestampMs,
                                        isAutomated = it.isAutomated,
                                        activityMode = it.activityMode.coerceIn(0, 2),
                                    )
                                },
                        )
                        historyUpdated = true
                        Timber.d("Received basal history: %d records", count)
                    }
                }

                WearDataContract.BOLUS_HISTORY_PATH -> {
                    val data = dataMap.getByteArray(WearDataContract.KEY_HISTORY_DATA)
                    val count = dataMap.getInt(WearDataContract.KEY_HISTORY_COUNT, 0)
                    if (data != null && count > 0 && count <= MAX_HISTORY_RECORDS) {
                        val records = WearHistorySerializer.decodeBolusHistory(data, count)
                        WatchDataRepository.updateBolusHistory(
                            records.filter { it.timestampMs > 0 && it.units >= 0f }
                                .map {
                                    WatchDataRepository.BolusHistoryRecord(
                                        units = it.units,
                                        correctionUnits = it.correctionUnits,
                                        mealUnits = it.mealUnits,
                                        timestampMs = it.timestampMs,
                                        isAutomated = it.isAutomated,
                                        isCorrection = it.isCorrection,
                                    )
                                },
                        )
                        historyUpdated = true
                        Timber.d("Received bolus history: %d records", count)
                    }
                }

                WearDataContract.IOB_HISTORY_PATH -> {
                    val data = dataMap.getByteArray(WearDataContract.KEY_HISTORY_DATA)
                    val count = dataMap.getInt(WearDataContract.KEY_HISTORY_COUNT, 0)
                    if (data != null && count > 0 && count <= MAX_HISTORY_RECORDS) {
                        val records = WearHistorySerializer.decodeIoBHistory(data, count)
                        WatchDataRepository.updateIoBHistory(
                            records.filter { it.timestampMs > 0 && it.iob >= 0f }
                                .map {
                                    WatchDataRepository.IoBHistoryRecord(
                                        iob = it.iob,
                                        timestampMs = it.timestampMs,
                                    )
                                },
                        )
                        historyUpdated = true
                        Timber.d("Received IoB history: %d records", count)
                    }
                }

                WearDataContract.IOB_PATH -> {
                    WatchDataRepository.updateIoB(
                        iob = dataMap.getFloat(WearDataContract.KEY_IOB_VALUE),
                        timestampMs = dataMap.getLong(WearDataContract.KEY_IOB_TIMESTAMP),
                    )
                    iobUpdated = true
                    Timber.d("Received IoB update from phone")
                }

                WearDataContract.CGM_PATH -> {
                    val mgDl = dataMap.getInt(WearDataContract.KEY_CGM_MG_DL)
                    if (!GlucoseDisplayUtils.isValidGlucose(mgDl)) {
                        Timber.w("Rejected invalid CGM value from phone")
                        return@forEach
                    }
                    val thresholds = sanitizeThresholds(
                        rawLow = dataMap.getInt(WearDataContract.KEY_GLUCOSE_LOW, 70),
                        rawHigh = dataMap.getInt(WearDataContract.KEY_GLUCOSE_HIGH, 180),
                        rawUrgentLow = dataMap.getInt(WearDataContract.KEY_GLUCOSE_URGENT_LOW, 55),
                        rawUrgentHigh = dataMap.getInt(WearDataContract.KEY_GLUCOSE_URGENT_HIGH, 250),
                    )
                    WatchDataRepository.updateCgm(
                        mgDl = mgDl,
                        trend = dataMap.getString(WearDataContract.KEY_CGM_TREND, "UNKNOWN"),
                        timestampMs = dataMap.getLong(WearDataContract.KEY_CGM_TIMESTAMP),
                        low = thresholds.low,
                        high = thresholds.high,
                        urgentLow = thresholds.urgentLow,
                        urgentHigh = thresholds.urgentHigh,
                    )
                    cgmUpdated = true
                    Timber.d("Received CGM update from phone")
                }

                WearDataContract.ALERT_PATH -> {
                    val alertType = dataMap.getString(WearDataContract.KEY_ALERT_TYPE, "none")
                    val alertsEnabled = WatchDataRepository.watchFaceConfig.value.showAlert
                    val rawBg = dataMap.getInt(WearDataContract.KEY_ALERT_BG_VALUE, 0)
                    val bgValue = if (GlucoseDisplayUtils.isValidGlucose(rawBg)) rawBg else 0
                    WatchDataRepository.updateAlert(
                        type = alertType,
                        bgValue = bgValue,
                        timestampMs = dataMap.getLong(WearDataContract.KEY_ALERT_TIMESTAMP),
                        message = dataMap.getString(WearDataContract.KEY_ALERT_MESSAGE, ""),
                    )
                    if (alertType != "none" && alertsEnabled) {
                        vibrateForAlert(alertType)
                    }
                    Timber.d("Received alert from phone: %s (vibrate=%b)", alertType, alertsEnabled)
                }
            }
        }

        if (configUpdated) {
            // Config change may affect which complications are visible
            requestComplicationUpdate(IoBComplicationDataSource::class.java)
        }
        if (iobUpdated) {
            requestComplicationUpdate(IoBComplicationDataSource::class.java)
        }
        if (cgmUpdated) {
            requestComplicationUpdate(BgComplicationDataSource::class.java)
            requestComplicationUpdate(GraphComplicationDataSource::class.java)
        }
        if (historyUpdated) {
            requestComplicationUpdate(GraphComplicationDataSource::class.java)
        }
    }

    override fun onMessageReceived(messageEvent: MessageEvent) {
        when (messageEvent.path) {
            WearDataContract.CHAT_RESPONSE_PATH -> {
                val responseData = messageEvent.data
                if (responseData == null) {
                    WatchDataRepository.setChatError("Empty response")
                    Timber.w("Received chat response with null data")
                    return
                }
                try {
                    val json = JSONObject(String(responseData, Charsets.UTF_8))
                    val response = json.optString("response", "")
                    val disclaimer = json.optString("disclaimer", "")
                    if (response.isBlank()) {
                        WatchDataRepository.setChatError("Empty response from AI")
                        return
                    }
                    WatchDataRepository.setChatResponse(response, disclaimer)
                    Timber.d("Received chat response from phone (%d chars)", response.length)
                } catch (e: Exception) {
                    Timber.w(e, "Failed to parse chat response")
                    WatchDataRepository.setChatError("Failed to parse response")
                }
            }

            WearDataContract.CHAT_ERROR_PATH -> {
                val data = messageEvent.data
                if (data == null) {
                    WatchDataRepository.setChatError("Unknown error")
                    Timber.w("Received chat error with null data")
                    return
                }
                val rawError = String(data, Charsets.UTF_8)
                // Cap error message length to avoid displaying stack traces or internal details
                val errorMsg = if (rawError.length > MAX_ERROR_LENGTH) {
                    rawError.take(MAX_ERROR_LENGTH) + "..."
                } else {
                    rawError
                }
                WatchDataRepository.setChatError(errorMsg)
                Timber.d("Received chat error from phone (%d chars)", rawError.length)
            }

            else -> super.onMessageReceived(messageEvent)
        }
    }

    private fun vibrateForAlert(alertType: String) {
        try {
            val manager = getSystemService(VIBRATOR_MANAGER_SERVICE) as VibratorManager
            val vibrator = manager.defaultVibrator

            val effect = if (alertType.startsWith("urgent")) {
                VibrationEffect.createWaveform(longArrayOf(0, 500, 200, 500), -1)
            } else {
                VibrationEffect.createOneShot(300, VibrationEffect.DEFAULT_AMPLITUDE)
            }
            vibrator.vibrate(effect)
        } catch (e: Exception) {
            Timber.w(e, "Failed to vibrate for alert")
        }
    }

    private companion object {
        const val MAX_ERROR_LENGTH = 200
        const val MAX_HISTORY_RECORDS = 500
    }

    private fun requestComplicationUpdate(dataSourceClass: Class<*>) {
        try {
            val requester = ComplicationDataSourceUpdateRequester.create(
                context = applicationContext,
                complicationDataSourceComponent = ComponentName(applicationContext, dataSourceClass),
            )
            requester.requestUpdateAll()
        } catch (e: Exception) {
            Timber.w(e, "Failed to request complication update for %s", dataSourceClass.simpleName)
        }
    }
}
