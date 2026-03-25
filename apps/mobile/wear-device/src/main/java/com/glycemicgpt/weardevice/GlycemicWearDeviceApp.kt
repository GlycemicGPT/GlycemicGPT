package com.glycemicgpt.weardevice

import android.app.Application
import com.glycemicgpt.weardevice.data.WatchDataRepository
import com.glycemicgpt.weardevice.data.WatchVersionPublisher
import com.glycemicgpt.weardevice.data.WearDataContract
import com.glycemicgpt.weardevice.util.GlucoseDisplayUtils
import com.glycemicgpt.weardevice.util.GlucoseDisplayUtils.sanitizeThresholds
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.Wearable
import dagger.hilt.android.HiltAndroidApp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import timber.log.Timber

@HiltAndroidApp
class GlycemicWearDeviceApp : Application() {

    override fun onCreate() {
        super.onCreate()
        if (BuildConfig.DEBUG) {
            Timber.plant(Timber.DebugTree())
        }
        // Initialize persistent cache before DataLayer bootstrap so
        // complication providers see restored data immediately on cold start.
        WatchDataRepository.init(this)
        bootstrapDataFromDataLayer()
        publishVersion()
    }

    private fun publishVersion() {
        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            WatchVersionPublisher.publish(this@GlycemicWearDeviceApp)
        }
    }

    private fun bootstrapDataFromDataLayer() {
        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            try {
                val dataClient = Wearable.getDataClient(this@GlycemicWearDeviceApp)
                val dataItems = dataClient.dataItems.await()
                try {
                    dataItems.forEach { item ->
                        val dataMap = DataMapItem.fromDataItem(item).dataMap
                        when (item.uri.path) {
                            WearDataContract.IOB_PATH -> {
                                WatchDataRepository.updateIoB(
                                    iob = dataMap.getFloat(WearDataContract.KEY_IOB_VALUE),
                                    timestampMs = dataMap.getLong(WearDataContract.KEY_IOB_TIMESTAMP),
                                )
                                Timber.d("Bootstrapped IoB from DataLayer cache")
                            }
                            WearDataContract.CGM_PATH -> {
                                val mgDl = dataMap.getInt(WearDataContract.KEY_CGM_MG_DL)
                                if (!GlucoseDisplayUtils.isValidGlucose(mgDl)) {
                                    Timber.w("Rejected invalid cached CGM value during bootstrap")
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
                                Timber.d("Bootstrapped CGM from DataLayer cache")
                            }
                            WearDataContract.ALERT_PATH -> {
                                WatchDataRepository.updateAlert(
                                    type = dataMap.getString(WearDataContract.KEY_ALERT_TYPE, "none"),
                                    bgValue = dataMap.getInt(WearDataContract.KEY_ALERT_BG_VALUE, 0),
                                    timestampMs = dataMap.getLong(WearDataContract.KEY_ALERT_TIMESTAMP),
                                    message = dataMap.getString(WearDataContract.KEY_ALERT_MESSAGE, ""),
                                )
                                Timber.d("Bootstrapped alert from DataLayer cache")
                            }
                        }
                    }
                } finally {
                    dataItems.release()
                }
            } catch (e: Exception) {
                Timber.w(e, "Failed to bootstrap watch data from DataLayer")
            }
        }
    }
}
