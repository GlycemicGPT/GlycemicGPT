package com.glycemicgpt.weardevice.complications

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.Path
import com.glycemicgpt.weardevice.data.WatchDataRepository
import com.glycemicgpt.weardevice.util.GlucoseDisplayUtils

object WatchGraphRenderer {

    const val IMG_WIDTH = 400
    const val IMG_HEIGHT = 100
    private const val PADDING = 4f

    // Overlay regions
    private const val BASAL_AREA_HEIGHT = 15f
    private const val IOB_AREA_HEIGHT = 20f
    private const val BOLUS_MARKER_HEIGHT = 8f

    // Line widths
    private const val GLUCOSE_LINE_WIDTH = 2f
    private const val GLUCOSE_DOT_RADIUS = 2f
    private const val THRESHOLD_LINE_WIDTH = 0.5f

    // Basal colors
    private const val BASAL_AUTOMATED = 0xFF00BCD4.toInt()   // Teal
    private const val BASAL_MANUAL = 0xFF78909C.toInt()       // Blue-grey
    private const val BASAL_SLEEP = 0xFF7E57C2.toInt()        // Purple
    private const val BASAL_EXERCISE = 0xFFFF9800.toInt()     // Orange

    // Bolus colors
    private const val BOLUS_AUTO_CORRECTION = 0xFFE91E63.toInt() // Pink
    private const val BOLUS_CORRECTION = 0xFFFF5722.toInt()      // Orange
    private const val BOLUS_MEAL = 0xFF7C4DFF.toInt()            // Purple

    // Mode overlay colors (full height, low alpha)
    private const val MODE_SLEEP_COLOR = 0x0F7E57C2.toInt()    // Purple, 0.06 alpha
    private const val MODE_EXERCISE_COLOR = 0x0FFF9800.toInt()  // Orange, 0.06 alpha

    // IoB color
    private const val IOB_LINE_COLOR = 0xFF42A5F5.toInt()      // Blue
    private const val IOB_FILL_COLOR = 0x2642A5F5              // Blue, 0.15 alpha

    data class GraphConfig(
        val showBasalOverlay: Boolean = true,
        val showBolusMarkers: Boolean = true,
        val showIoBOverlay: Boolean = true,
        val showModeBands: Boolean = true,
    )

    fun render(
        cgmReadings: List<WatchDataRepository.CgmState>,
        basalHistory: List<WatchDataRepository.BasalHistoryRecord>,
        bolusHistory: List<WatchDataRepository.BolusHistoryRecord>,
        iobHistory: List<WatchDataRepository.IoBHistoryRecord>,
        low: Int,
        high: Int,
        config: GraphConfig = GraphConfig(),
    ): Bitmap {
        val bitmap = Bitmap.createBitmap(IMG_WIDTH, IMG_HEIGHT, Bitmap.Config.ARGB_8888)
        if (cgmReadings.isEmpty()) return bitmap

        val canvas = Canvas(bitmap)

        val graphLeft = PADDING
        val graphRight = IMG_WIDTH - PADDING
        val graphTop = PADDING
        val graphBottom = IMG_HEIGHT - PADDING
        val graphWidth = graphRight - graphLeft
        val graphHeight = graphBottom - graphTop

        // Y-axis range for glucose
        val values = cgmReadings.map { it.mgDl }
        val minY = minOf(values.min(), low - 10).coerceAtLeast(20)
        val maxY = maxOf(values.max(), high + 10).coerceAtMost(500)
        val yRange = (maxY - minY).toFloat().coerceAtLeast(1f)

        // X-axis range
        val minX = cgmReadings.first().timestampMs
        val maxX = cgmReadings.last().timestampMs
        val xRange = (maxX - minX).toFloat().coerceAtLeast(1f)

        fun xPos(timestampMs: Long): Float =
            graphLeft + ((timestampMs - minX) / xRange) * graphWidth

        fun yPos(mgDl: Int): Float =
            graphBottom - ((mgDl - minY) / yRange) * graphHeight

        // 1. Mode bands (sleep/exercise) -- full height
        if (config.showModeBands && basalHistory.isNotEmpty()) {
            drawModeBands(canvas, basalHistory, graphLeft, graphTop, graphRight, graphBottom, ::xPos)
        }

        // 2. Target range band
        val rangePaint = Paint().apply {
            color = 0x1F22C55E // Green fill, 0.12 alpha
            style = Paint.Style.FILL
        }
        val lowY = yPos(low)
        val highY = yPos(high)
        canvas.drawRect(graphLeft, highY, graphRight, lowY, rangePaint)

        // 3. Threshold dashed lines
        val thresholdPaint = Paint().apply {
            color = 0x80FFFFFF.toInt()
            strokeWidth = THRESHOLD_LINE_WIDTH
            style = Paint.Style.STROKE
            pathEffect = DashPathEffect(floatArrayOf(4f, 4f), 0f)
        }
        canvas.drawLine(graphLeft, lowY, graphRight, lowY, thresholdPaint)
        canvas.drawLine(graphLeft, highY, graphRight, highY, thresholdPaint)

        // 4. Basal stepped area (bottom region)
        if (config.showBasalOverlay && basalHistory.isNotEmpty()) {
            drawBasalArea(canvas, basalHistory, graphLeft, graphBottom, graphRight, ::xPos)
        }

        // 5. IoB overlay (bottom region, slightly overlapping basal)
        if (config.showIoBOverlay && iobHistory.isNotEmpty()) {
            drawIoBArea(canvas, iobHistory, graphLeft, graphBottom, graphRight, ::xPos)
        }

        // 6. Bolus markers (top region)
        if (config.showBolusMarkers && bolusHistory.isNotEmpty()) {
            drawBolusMarkers(canvas, bolusHistory, graphTop, ::xPos)
        }

        // 7. Glucose line + dots
        drawGlucoseLine(canvas, cgmReadings, ::xPos, ::yPos)

        return bitmap
    }

    private fun drawModeBands(
        canvas: Canvas,
        basalHistory: List<WatchDataRepository.BasalHistoryRecord>,
        graphLeft: Float,
        graphTop: Float,
        graphRight: Float,
        graphBottom: Float,
        xPos: (Long) -> Float,
    ) {
        val paint = Paint().apply { style = Paint.Style.FILL }
        val sorted = basalHistory.sortedBy { it.timestampMs }

        for (i in sorted.indices) {
            val record = sorted[i]
            if (record.activityMode == 0) continue // NONE
            paint.color = when (record.activityMode) {
                1 -> MODE_SLEEP_COLOR
                2 -> MODE_EXERCISE_COLOR
                else -> continue
            }
            val x1 = xPos(record.timestampMs).coerceIn(graphLeft, graphRight)
            val x2 = if (i + 1 < sorted.size) {
                xPos(sorted[i + 1].timestampMs).coerceIn(graphLeft, graphRight)
            } else {
                graphRight
            }
            if (x2 > x1) {
                canvas.drawRect(x1, graphTop, x2, graphBottom, paint)
            }
        }
    }

    private fun drawBasalArea(
        canvas: Canvas,
        basalHistory: List<WatchDataRepository.BasalHistoryRecord>,
        graphLeft: Float,
        graphBottom: Float,
        graphRight: Float,
        xPos: (Long) -> Float,
    ) {
        val sorted = basalHistory.sortedBy { it.timestampMs }
        if (sorted.isEmpty()) return

        val maxRate = sorted.maxOf { it.rate }.coerceAtLeast(0.1f)
        val basalTop = graphBottom - BASAL_AREA_HEIGHT

        val fillPaint = Paint().apply {
            style = Paint.Style.FILL
            alpha = 38 // ~0.15
        }

        for (i in sorted.indices) {
            val record = sorted[i]
            fillPaint.color = basalColor(record.isAutomated, record.activityMode)
            fillPaint.alpha = 38

            val height = (record.rate / maxRate) * BASAL_AREA_HEIGHT
            val y = graphBottom - height

            val x1 = xPos(record.timestampMs).coerceIn(graphLeft, graphRight)
            val x2 = if (i + 1 < sorted.size) {
                xPos(sorted[i + 1].timestampMs).coerceIn(graphLeft, graphRight)
            } else {
                graphRight
            }
            if (x2 > x1) {
                canvas.drawRect(x1, y, x2, graphBottom, fillPaint)
            }
        }
    }

    private fun basalColor(isAutomated: Boolean, activityMode: Int): Int = when {
        activityMode == 1 -> BASAL_SLEEP
        activityMode == 2 -> BASAL_EXERCISE
        isAutomated -> BASAL_AUTOMATED
        else -> BASAL_MANUAL
    }

    private fun drawIoBArea(
        canvas: Canvas,
        iobHistory: List<WatchDataRepository.IoBHistoryRecord>,
        graphLeft: Float,
        graphBottom: Float,
        graphRight: Float,
        xPos: (Long) -> Float,
    ) {
        val sorted = iobHistory.sortedBy { it.timestampMs }
        if (sorted.isEmpty()) return

        val maxIoB = sorted.maxOf { it.iob }.coerceAtLeast(0.1f)

        val fillPaint = Paint().apply {
            color = IOB_FILL_COLOR
            style = Paint.Style.FILL
        }
        val linePaint = Paint().apply {
            color = IOB_LINE_COLOR
            strokeWidth = 1.5f
            style = Paint.Style.STROKE
            isAntiAlias = true
        }

        val fillPath = Path()
        val linePath = Path()
        var started = false

        for (record in sorted) {
            val x = xPos(record.timestampMs).coerceIn(graphLeft, graphRight)
            val height = (record.iob / maxIoB) * IOB_AREA_HEIGHT
            val y = graphBottom - height

            if (!started) {
                fillPath.moveTo(x, graphBottom)
                fillPath.lineTo(x, y)
                linePath.moveTo(x, y)
                started = true
            } else {
                fillPath.lineTo(x, y)
                linePath.lineTo(x, y)
            }
        }

        // Close fill path
        val lastX = xPos(sorted.last().timestampMs).coerceIn(graphLeft, graphRight)
        fillPath.lineTo(lastX, graphBottom)
        fillPath.close()

        canvas.drawPath(fillPath, fillPaint)
        canvas.drawPath(linePath, linePaint)
    }

    private fun drawBolusMarkers(
        canvas: Canvas,
        bolusHistory: List<WatchDataRepository.BolusHistoryRecord>,
        graphTop: Float,
        xPos: (Long) -> Float,
    ) {
        val paint = Paint().apply {
            style = Paint.Style.FILL
            isAntiAlias = true
        }

        val markerCenterY = graphTop + BOLUS_MARKER_HEIGHT / 2f
        val halfSize = 1.5f // diamond half-width

        for (record in bolusHistory) {
            paint.color = bolusColor(record.isAutomated, record.isCorrection, record.mealUnits)
            val x = xPos(record.timestampMs)

            val path = Path().apply {
                moveTo(x, markerCenterY - halfSize * 2) // top
                lineTo(x + halfSize, markerCenterY)     // right
                lineTo(x, markerCenterY + halfSize * 2) // bottom
                lineTo(x - halfSize, markerCenterY)     // left
                close()
            }
            canvas.drawPath(path, paint)
        }
    }

    private fun bolusColor(isAutomated: Boolean, isCorrection: Boolean, mealUnits: Float): Int =
        when {
            isAutomated && isCorrection -> BOLUS_AUTO_CORRECTION
            isCorrection -> BOLUS_CORRECTION
            mealUnits > 0f -> BOLUS_MEAL
            else -> BOLUS_CORRECTION
        }

    private fun drawGlucoseLine(
        canvas: Canvas,
        readings: List<WatchDataRepository.CgmState>,
        xPos: (Long) -> Float,
        yPos: (Int) -> Float,
    ) {
        val linePaint = Paint().apply {
            strokeWidth = GLUCOSE_LINE_WIDTH
            isAntiAlias = true
            style = Paint.Style.STROKE
            strokeCap = Paint.Cap.ROUND
        }
        val dotPaint = Paint().apply {
            isAntiAlias = true
            style = Paint.Style.FILL
        }

        for (i in 0 until readings.size - 1) {
            val r1 = readings[i]
            val r2 = readings[i + 1]
            val x1 = xPos(r1.timestampMs)
            val y1 = yPos(r1.mgDl)
            val x2 = xPos(r2.timestampMs)
            val y2 = yPos(r2.mgDl)

            linePaint.color = GlucoseDisplayUtils.bgColor(
                r1.mgDl, r1.low, r1.high, r1.urgentLow, r1.urgentHigh,
            )
            canvas.drawLine(x1, y1, x2, y2, linePaint)
        }

        for (r in readings) {
            val x = xPos(r.timestampMs)
            val y = yPos(r.mgDl)
            dotPaint.color = GlucoseDisplayUtils.bgColor(
                r.mgDl, r.low, r.high, r.urgentLow, r.urgentHigh,
            )
            canvas.drawCircle(x, y, GLUCOSE_DOT_RADIUS, dotPaint)
        }
    }

    fun renderPreview(): Bitmap {
        val now = System.currentTimeMillis()
        val fakeReadings = listOf(120, 135, 150, 145, 160, 155, 140, 130, 125, 110, 105, 115)
            .mapIndexed { i, bg ->
                WatchDataRepository.CgmState(
                    mgDl = bg, trend = "FLAT",
                    timestampMs = now - (12 - i) * 300_000L,
                    low = 70, high = 180, urgentLow = 55, urgentHigh = 250,
                )
            }
        val fakeBasal = listOf(
            WatchDataRepository.BasalHistoryRecord(0.8f, now - 3_600_000L * 3, true, 0),
            WatchDataRepository.BasalHistoryRecord(1.2f, now - 3_600_000L * 2, true, 0),
            WatchDataRepository.BasalHistoryRecord(0.5f, now - 3_600_000L, false, 1),
            WatchDataRepository.BasalHistoryRecord(0.9f, now - 1_800_000L, true, 0),
        )
        val fakeBolus = listOf(
            WatchDataRepository.BolusHistoryRecord(2.5f, 0f, 2.5f, now - 7_200_000L, false, false),
            WatchDataRepository.BolusHistoryRecord(0.3f, 0.3f, 0f, now - 3_600_000L, true, true),
        )
        val fakeIoB = listOf(
            WatchDataRepository.IoBHistoryRecord(3.2f, now - 3_600_000L * 3),
            WatchDataRepository.IoBHistoryRecord(2.5f, now - 3_600_000L * 2),
            WatchDataRepository.IoBHistoryRecord(1.8f, now - 3_600_000L),
            WatchDataRepository.IoBHistoryRecord(0.9f, now - 1_800_000L),
        )
        return render(fakeReadings, fakeBasal, fakeBolus, fakeIoB, 70, 180)
    }
}
