package com.glycemicgpt.weardevice.complications

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
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
import com.glycemicgpt.weardevice.util.GlucoseDisplayUtils

class GraphComplicationDataSource : SuspendingComplicationDataSourceService() {

    companion object {
        private const val IMG_WIDTH = 400
        private const val IMG_HEIGHT = 100
        private const val PADDING = 4f
        private const val LINE_WIDTH = 3f
        private const val RANGE_LINE_WIDTH = 1f
        private const val MIN_READINGS = 3
    }

    override fun getPreviewData(type: ComplicationType): ComplicationData {
        if (type != ComplicationType.SMALL_IMAGE) return NoDataComplicationData()
        val bitmap = renderPreviewGraph()
        val icon = Icon.createWithBitmap(bitmap)
        bitmap.recycle()
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

        val low = readings.first().low
        val high = readings.first().high
        val bitmap = renderGraph(readings, low, high)

        val icon = Icon.createWithBitmap(bitmap)
        bitmap.recycle()
        return SmallImageComplicationData.Builder(
            smallImage = SmallImage.Builder(icon, SmallImageType.PHOTO).build(),
            contentDescription = PlainComplicationText.Builder(
                "Glucose trend: ${readings.size} readings over ${config.graphRangeHours}h"
            ).build(),
        ).build()
    }

    private fun renderGraph(
        readings: List<WatchDataRepository.CgmState>,
        low: Int,
        high: Int,
    ): Bitmap {
        val bitmap = Bitmap.createBitmap(IMG_WIDTH, IMG_HEIGHT, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)

        // Graph area
        val graphLeft = PADDING
        val graphRight = IMG_WIDTH - PADDING
        val graphTop = PADDING
        val graphBottom = IMG_HEIGHT - PADDING
        val graphWidth = graphRight - graphLeft
        val graphHeight = graphBottom - graphTop

        // Y-axis range: use glucose range with padding
        val values = readings.map { it.mgDl }
        val minY = minOf(values.min(), low - 10).coerceAtLeast(20)
        val maxY = maxOf(values.max(), high + 10).coerceAtMost(400)
        val yRange = (maxY - minY).toFloat().coerceAtLeast(1f)

        // X-axis range
        val minX = readings.first().timestampMs
        val maxX = readings.last().timestampMs
        val xRange = (maxX - minX).toFloat().coerceAtLeast(1f)

        // Draw range band (green zone between low and high)
        val rangePaint = Paint().apply {
            color = 0x3322C55E // Semi-transparent green
            style = Paint.Style.FILL
        }
        val lowY = graphBottom - ((low - minY) / yRange) * graphHeight
        val highY = graphBottom - ((high - minY) / yRange) * graphHeight
        canvas.drawRect(graphLeft, highY, graphRight, lowY, rangePaint)

        // Draw range lines (low and high thresholds)
        val rangeLinePaint = Paint().apply {
            color = 0x66FFFFFF // Semi-transparent white
            strokeWidth = RANGE_LINE_WIDTH
            style = Paint.Style.STROKE
        }
        canvas.drawLine(graphLeft, lowY, graphRight, lowY, rangeLinePaint)
        canvas.drawLine(graphLeft, highY, graphRight, highY, rangeLinePaint)

        // Draw glucose line with color segments
        val linePaint = Paint().apply {
            strokeWidth = LINE_WIDTH
            isAntiAlias = true
            style = Paint.Style.STROKE
            strokeCap = Paint.Cap.ROUND
        }
        for (i in 0 until readings.size - 1) {
            val r1 = readings[i]
            val r2 = readings[i + 1]

            val x1 = graphLeft + ((r1.timestampMs - minX) / xRange) * graphWidth
            val y1 = graphBottom - ((r1.mgDl - minY) / yRange) * graphHeight
            val x2 = graphLeft + ((r2.timestampMs - minX) / xRange) * graphWidth
            val y2 = graphBottom - ((r2.mgDl - minY) / yRange) * graphHeight

            linePaint.color = GlucoseDisplayUtils.bgColor(
                r1.mgDl, r1.low, r1.high, r1.urgentLow, r1.urgentHigh
            )
            canvas.drawLine(x1, y1, x2, y2, linePaint)
        }

        // Draw dots at each reading
        val dotPaint = Paint().apply {
            isAntiAlias = true
            style = Paint.Style.FILL
        }
        for (r in readings) {
            val x = graphLeft + ((r.timestampMs - minX) / xRange) * graphWidth
            val y = graphBottom - ((r.mgDl - minY) / yRange) * graphHeight
            dotPaint.color = GlucoseDisplayUtils.bgColor(r.mgDl, r.low, r.high, r.urgentLow, r.urgentHigh)
            canvas.drawCircle(x, y, 2.5f, dotPaint)
        }

        return bitmap
    }

    private fun renderPreviewGraph(): Bitmap {
        // Generate a fake sparkline for preview
        val now = System.currentTimeMillis()
        val fakeReadings = listOf(120, 135, 150, 145, 160, 155, 140, 130, 125, 110, 105, 115)
            .mapIndexed { i, bg ->
                WatchDataRepository.CgmState(
                    mgDl = bg, trend = "FLAT",
                    timestampMs = now - (12 - i) * 300_000L,
                    low = 70, high = 180, urgentLow = 55, urgentHigh = 250,
                )
            }
        return renderGraph(fakeReadings, 70, 180)
    }
}
