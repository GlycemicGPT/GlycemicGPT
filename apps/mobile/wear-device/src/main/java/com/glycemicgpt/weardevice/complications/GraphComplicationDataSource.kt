package com.glycemicgpt.weardevice.complications

import androidx.wear.watchface.complications.data.ComplicationData
import androidx.wear.watchface.complications.data.ComplicationType
import androidx.wear.watchface.complications.data.NoDataComplicationData
import androidx.wear.watchface.complications.data.PlainComplicationText
import androidx.wear.watchface.complications.data.SmallImage
import androidx.wear.watchface.complications.data.SmallImageComplicationData
import androidx.wear.watchface.complications.data.SmallImageType
import android.graphics.drawable.Icon
import androidx.wear.watchface.complications.datasource.ComplicationRequest
import androidx.wear.watchface.complications.datasource.SuspendingComplicationDataSourceService
import com.glycemicgpt.weardevice.data.WatchDataRepository

class GraphComplicationDataSource : SuspendingComplicationDataSourceService() {

    companion object {
        private const val MIN_READINGS = 3
    }

    override fun getPreviewData(type: ComplicationType): ComplicationData {
        if (type != ComplicationType.SMALL_IMAGE) return NoDataComplicationData()
        val bitmap = WatchGraphRenderer.renderPreview()
        val icon = Icon.createWithBitmap(bitmap)
        return SmallImageComplicationData.Builder(
            smallImage = SmallImage.Builder(icon, SmallImageType.PHOTO).build(),
            contentDescription = PlainComplicationText.Builder("Glucose trend graph preview").build(),
        ).build()
    }

    override suspend fun onComplicationRequest(request: ComplicationRequest): ComplicationData {
        if (request.complicationType != ComplicationType.SMALL_IMAGE) {
            return NoDataComplicationData()
        }

        val config = WatchDataRepository.watchFaceConfig.value
        if (!config.showGraph) return NoDataComplicationData()

        val history = WatchDataRepository.cgmHistory.value
        if (history.size < MIN_READINGS) return NoDataComplicationData()

        val rangeMs = config.graphRangeHours * 3_600_000L
        val cutoff = System.currentTimeMillis() - rangeMs
        val readings = history.filter { it.timestampMs >= cutoff }.sortedBy { it.timestampMs }
        if (readings.size < MIN_READINGS) return NoDataComplicationData()

        val low = readings.last().low
        val high = readings.last().high

        val basalHistory = WatchDataRepository.basalHistory.value
            .filter { it.timestampMs >= cutoff }
        val bolusHistory = WatchDataRepository.bolusHistory.value
            .filter { it.timestampMs >= cutoff }
        val iobHistory = WatchDataRepository.iobHistory.value
            .filter { it.timestampMs >= cutoff }

        val graphConfig = WatchGraphRenderer.GraphConfig(
            showBasalOverlay = config.showBasalOverlay,
            showBolusMarkers = config.showBolusMarkers,
            showIoBOverlay = config.showIoBOverlay,
            showModeBands = config.showModeBands,
        )

        val bitmap = WatchGraphRenderer.render(
            cgmReadings = readings,
            basalHistory = basalHistory,
            bolusHistory = bolusHistory,
            iobHistory = iobHistory,
            low = low,
            high = high,
            config = graphConfig,
        )

        val icon = Icon.createWithBitmap(bitmap)
        return SmallImageComplicationData.Builder(
            smallImage = SmallImage.Builder(icon, SmallImageType.PHOTO).build(),
            contentDescription = PlainComplicationText.Builder(
                "Glucose trend: ${readings.size} readings over ${config.graphRangeHours}h"
            ).build(),
        ).build()
    }
}
