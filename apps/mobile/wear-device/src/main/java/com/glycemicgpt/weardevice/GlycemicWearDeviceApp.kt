package com.glycemicgpt.weardevice

import android.app.Application
import com.glycemicgpt.weardevice.data.WatchDataRepository
import com.glycemicgpt.weardevice.data.WearDataContract
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
        bootstrapDataFromDataLayer()
    }

    private fun bootstrapDataFromDataLayer() {
        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            try {
                val dataClient = Wearable.getDataClient(this@GlycemicWearDeviceApp)
                val dataItems = dataClient.dataItems.await()
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
                            WatchDataRepository.updateCgm(
                                mgDl = dataMap.getInt(WearDataContract.KEY_CGM_MG_DL),
                                trend = dataMap.getString(WearDataContract.KEY_CGM_TREND, "UNKNOWN"),
                                timestampMs = dataMap.getLong(WearDataContract.KEY_CGM_TIMESTAMP),
                                low = dataMap.getInt(WearDataContract.KEY_GLUCOSE_LOW, 70),
                                high = dataMap.getInt(WearDataContract.KEY_GLUCOSE_HIGH, 180),
                                urgentLow = dataMap.getInt(WearDataContract.KEY_GLUCOSE_URGENT_LOW, 55),
                                urgentHigh = dataMap.getInt(WearDataContract.KEY_GLUCOSE_URGENT_HIGH, 250),
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
                dataItems.release()
            } catch (e: Exception) {
                Timber.w(e, "Failed to bootstrap watch data from DataLayer")
            }
        }
    }
}
