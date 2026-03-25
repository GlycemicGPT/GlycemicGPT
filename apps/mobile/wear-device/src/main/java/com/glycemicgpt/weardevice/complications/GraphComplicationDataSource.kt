package com.glycemicgpt.weardevice.complications

import android.app.PendingIntent
import android.content.Intent
import android.graphics.drawable.Icon
import androidx.wear.watchface.complications.data.ComplicationData
import androidx.wear.watchface.complications.data.ComplicationType
import androidx.wear.watchface.complications.data.NoDataComplicationData
import androidx.wear.watchface.complications.data.PlainComplicationText
import androidx.wear.watchface.complications.data.SmallImage
import androidx.wear.watchface.complications.data.SmallImageComplicationData
import androidx.wear.watchface.complications.data.SmallImageType
import androidx.wear.watchface.complications.datasource.ComplicationRequest
import androidx.wear.watchface.complications.datasource.SuspendingComplicationDataSourceService
import com.glycemicgpt.weardevice.data.WatchDataRepository
import com.glycemicgpt.weardevice.presentation.GraphDetailActivity
import java.util.Objects

class GraphComplicationDataSource : SuspendingComplicationDataSourceService() {

    companion object {
        private const val MIN_READINGS = 3
        private const val GRAPH_REQUEST_CODE = 2000
    }

    private var cachedBitmap: android.graphics.Bitmap? = null
    private var cachedDataHash: Int = 0

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

        // Ensure persisted data is restored -- the complication service may be
        // invoked in a fresh process before Application.onCreate() runs.
        WatchDataRepository.init(applicationContext)

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

        val basalHistory = if (config.showBasalOverlay || config.showModeBands) {
            WatchDataRepository.basalHistory.value.filter { it.timestampMs >= cutoff }
        } else {
            emptyList()
        }
        val bolusHistory = emptyList<WatchDataRepository.BolusHistoryRecord>() // too small at 400x100
        val iobHistory = if (config.showIoBOverlay) {
            WatchDataRepository.iobHistory.value.filter { it.timestampMs >= cutoff }
        } else {
            emptyList()
        }

        val graphConfig = WatchGraphRenderer.GraphConfig(
            showBasalOverlay = config.showBasalOverlay,
            showBolusMarkers = false, // too small for bolus markers at 400x100
            showIoBOverlay = config.showIoBOverlay,
            showModeBands = config.showModeBands,
        )

        // Cache the rendered bitmap and only re-render when data changes.
        // Only include data that the renderer actually uses based on config
        // to avoid unnecessary re-renders when non-visible data changes.
        val dataHash = Objects.hash(
            readings,
            if (config.showBasalOverlay || config.showModeBands) basalHistory else null,
            if (config.showIoBOverlay) iobHistory else null,
            graphConfig,
            low,
            high,
        )

        val bitmap = if (dataHash == cachedDataHash && cachedBitmap != null) {
            cachedBitmap!!
        } else {
            WatchGraphRenderer.render(
                cgmReadings = readings,
                basalHistory = basalHistory,
                bolusHistory = bolusHistory,
                iobHistory = iobHistory,
                low = low,
                high = high,
                config = graphConfig,
            ).also {
                cachedBitmap = it
                cachedDataHash = dataHash
            }
        }

        val icon = Icon.createWithBitmap(bitmap)

        val tapIntent = Intent(this, GraphDetailActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        }
        val tapAction = PendingIntent.getActivity(
            this,
            GRAPH_REQUEST_CODE,
            tapIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        return SmallImageComplicationData.Builder(
            smallImage = SmallImage.Builder(icon, SmallImageType.PHOTO).build(),
            contentDescription = PlainComplicationText.Builder(
                "Glucose trend: ${readings.size} readings over ${config.graphRangeHours}h"
            ).build(),
        )
            .setTapAction(tapAction)
            .build()
    }
}
