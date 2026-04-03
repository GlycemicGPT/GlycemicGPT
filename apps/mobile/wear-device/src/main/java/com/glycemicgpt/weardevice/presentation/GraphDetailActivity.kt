package com.glycemicgpt.weardevice.presentation

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Fill
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Scaffold
import androidx.wear.compose.material.Text
import androidx.wear.compose.material.TimeText
import com.glycemicgpt.weardevice.data.WatchDataRepository
import com.glycemicgpt.weardevice.util.GlucoseDisplayUtils
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

// -- Pre-allocated Paint objects (Issue 6: avoid allocating inside DrawScope) --

private object GraphPaints {
    val thresholdLabel: android.graphics.Paint by lazy {
        android.graphics.Paint().apply {
            color = 0xB3FFFFFF.toInt() // white, 0.7 alpha
            textSize = 20f
            isAntiAlias = true
            textAlign = android.graphics.Paint.Align.RIGHT
            isFakeBoldText = true
        }
    }

    val bolusLabel: android.graphics.Paint by lazy {
        android.graphics.Paint().apply {
            color = android.graphics.Color.WHITE
            textSize = 16f
            isAntiAlias = true
            textAlign = android.graphics.Paint.Align.CENTER
            isFakeBoldText = true
        }
    }

    val timeAxisLabel: android.graphics.Paint by lazy {
        android.graphics.Paint().apply {
            color = 0x99FFFFFF.toInt() // white, 0.6 alpha
            textSize = 16f
            isAntiAlias = true
            textAlign = android.graphics.Paint.Align.CENTER
        }
    }

    val tooltipText: android.graphics.Paint by lazy {
        android.graphics.Paint().apply {
            color = android.graphics.Color.WHITE
            textSize = 22f
            isAntiAlias = true
            textAlign = android.graphics.Paint.Align.CENTER
            isFakeBoldText = true
        }
    }
}

// -- Pre-allocated SimpleDateFormat instances (Issue 13: avoid allocating in draw loop) --

private val timeAxisFormat: SimpleDateFormat by lazy {
    SimpleDateFormat("h:mm", Locale.getDefault())
}

private val tooltipTimeFormat: SimpleDateFormat by lazy {
    SimpleDateFormat("h:mm a", Locale.getDefault())
}

class GraphDetailActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            GraphDetailScreen()
        }
    }
}

private data class TooltipData(
    val text: String,
    val x: Float,
    val y: Float,
)

// -- Colors matching WatchGraphRenderer --

private val RANGE_BAND_COLOR = Color(0x1F22C55E) // Green, 0.12 alpha

private val BASAL_AUTOMATED = Color(0xFF00BCD4) // Teal
private val BASAL_MANUAL = Color(0xFF78909C) // Blue-grey
private val BASAL_SLEEP = Color(0xFF7E57C2) // Purple
private val BASAL_EXERCISE = Color(0xFFFF9800) // Orange

private val BOLUS_AUTO_CORRECTION = Color(0xFFE91E63) // Pink
private val BOLUS_CORRECTION = Color(0xFFFF5722) // Orange
private val BOLUS_MEAL = Color(0xFF7C4DFF) // Purple

private val IOB_LINE_COLOR = Color(0xFF42A5F5) // Blue
private val IOB_FILL_COLOR = Color(0x2642A5F5) // Blue, 0.15 alpha

private val MODE_SLEEP_COLOR = Color(0x0F7E57C2) // Purple, 0.06 alpha
private val MODE_EXERCISE_COLOR = Color(0x0FFF9800) // Orange, 0.06 alpha

// -- Layout constants --

private const val GRAPH_PADDING = 28f // left padding for Y-axis labels
private const val GRAPH_PADDING_RIGHT = 8f
private const val GRAPH_PADDING_TOP = 8f
private const val GRAPH_PADDING_BOTTOM = 20f // room for time-axis labels
private const val GLUCOSE_DOT_RADIUS = 5f
private const val GLUCOSE_LINE_WIDTH = 2f
private const val THRESHOLD_LINE_WIDTH = 1f
private const val BASAL_AREA_HEIGHT = 24f
private const val IOB_AREA_HEIGHT = 28f
private const val BOLUS_DIAMOND_HALF = 4f
private const val BOLUS_MARKER_TOP_OFFSET = 4f
private const val MIN_READINGS = 3

/** Squared distance threshold for tap detection (in pixels). */
private const val TAP_RADIUS_SQ = 2500f // 50px radius

private const val Y_MIN_DEFAULT = 40
private const val Y_MAX_DEFAULT = 400

@Composable
private fun GraphDetailScreen() {
    val config by WatchDataRepository.watchFaceConfig.collectAsState()
    val cgmHistory by WatchDataRepository.cgmHistory.collectAsState()
    val basalHistory by WatchDataRepository.basalHistory.collectAsState()
    val bolusHistory by WatchDataRepository.bolusHistory.collectAsState()
    val iobHistory by WatchDataRepository.iobHistory.collectAsState()
    val categoryLabels by WatchDataRepository.categoryLabels.collectAsState()

    val rangeMs = config.graphRangeHours * 3_600_000L
    val now = remember(cgmHistory, config.graphRangeHours) {
        System.currentTimeMillis()
    }

    // Use all available history (not just rangeMs) so there is data to pan into.
    val readings = remember(cgmHistory) {
        cgmHistory.sortedBy { it.timestampMs }
    }
    val dataStartMs = remember(readings) {
        readings.firstOrNull()?.timestampMs ?: (now - rangeMs)
    }
    val filteredBasal = remember(basalHistory) {
        basalHistory.sortedBy { it.timestampMs }
    }
    val filteredBolus = remember(bolusHistory) {
        bolusHistory.sortedBy { it.timestampMs }
    }
    val filteredIoB = remember(iobHistory) {
        iobHistory.sortedBy { it.timestampMs }
    }

    var tooltip by remember { mutableStateOf<TooltipData?>(null) }
    var panOffsetPx by remember { mutableFloatStateOf(0f) }

    MaterialTheme {
        Scaffold(timeText = { TimeText() }) {
            if (readings.size < MIN_READINGS) {
                Box(
                    modifier = Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = "Not enough data",
                        style = MaterialTheme.typography.body2,
                        textAlign = TextAlign.Center,
                    )
                }
            } else {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(top = 32.dp, start = 4.dp, end = 4.dp, bottom = 4.dp),
                ) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .weight(1f),
                    ) {
                        val low = readings.last().low
                        val high = readings.last().high

                        Canvas(
                            modifier = Modifier
                                .fillMaxSize()
                                .pointerInput(Unit) {
                                    detectDragGestures { _, dragAmount ->
                                        panOffsetPx += dragAmount.x
                                        // Clamp pan to prevent dead zones.
                                        // Positive pan = drag right = scroll back in time.
                                        // Lower bound: 0 (can't scroll past "now").
                                        // Upper bound: pixel offset where viewport
                                        // reaches earliest available data.
                                        val graphW = size.width.toFloat() -
                                            GRAPH_PADDING - GRAPH_PADDING_RIGHT
                                        val maxPanPx = if (graphW > 0f) {
                                            val scrollableMs = now - dataStartMs - rangeMs
                                            if (scrollableMs > 0L) {
                                                (scrollableMs.toFloat() /
                                                    rangeMs.toFloat()) * graphW
                                            } else {
                                                0f
                                            }
                                        } else {
                                            0f
                                        }
                                        panOffsetPx = panOffsetPx.coerceIn(0f, maxPanPx)
                                    }
                                }
                                .pointerInput(readings) {
                                    detectTapGestures { offset ->
                                        tooltip = findNearestReading(
                                            tapOffset = offset,
                                            readings = readings,
                                            canvasWidth = size.width.toFloat(),
                                            canvasHeight = size.height.toFloat(),
                                            panOffsetPx = panOffsetPx,
                                            viewportRangeMs = rangeMs,
                                            dataStartMs = dataStartMs,
                                            nowMs = now,
                                        )
                                    }
                                },
                        ) {
                            val graphLeft = GRAPH_PADDING
                            val graphRight = size.width - GRAPH_PADDING_RIGHT
                            val graphTop = GRAPH_PADDING_TOP
                            val graphBottom = size.height - GRAPH_PADDING_BOTTOM
                            val graphWidth = graphRight - graphLeft
                            val graphHeight = graphBottom - graphTop

                            // Compute viewport based on pan
                            val viewportInfo = computeViewport(
                                panOffsetPx = panOffsetPx,
                                graphWidth = graphWidth,
                                viewportRangeMs = rangeMs,
                                dataStartMs = dataStartMs,
                                nowMs = now,
                            )

                            // Y-axis range
                            val values = readings.map { it.mgDl }
                            val minY = minOf(
                                values.min(),
                                low - 10,
                            ).coerceAtLeast(Y_MIN_DEFAULT)
                            val maxY = maxOf(
                                values.max(),
                                high + 10,
                            ).coerceAtMost(Y_MAX_DEFAULT)
                            val yRange = (maxY - minY).toFloat().coerceAtLeast(1f)

                            fun xPos(timestampMs: Long): Float =
                                graphLeft + ((timestampMs - viewportInfo.startMs).toFloat() /
                                    viewportInfo.rangeMs.toFloat()) * graphWidth

                            fun yPos(mgDl: Int): Float =
                                graphBottom - ((mgDl - minY).toFloat() / yRange) * graphHeight

                            val graphRect = Rect(
                                left = graphLeft,
                                top = graphTop,
                                right = graphRight,
                                bottom = graphBottom,
                            )

                            // 1. Mode bands
                            if (config.showModeBands && filteredBasal.isNotEmpty()) {
                                drawModeBands(
                                    filteredBasal,
                                    graphRect,
                                    ::xPos,
                                )
                            }

                            // 2. Target range band
                            drawRangeBand(
                                low = low,
                                high = high,
                                graphRect = graphRect,
                                yPos = ::yPos,
                            )

                            // 3. Threshold lines with numbers
                            drawThresholdLines(
                                low = low,
                                high = high,
                                graphRect = graphRect,
                                yPos = ::yPos,
                            )

                            // 4. Basal stepped area
                            if (config.showBasalOverlay && filteredBasal.isNotEmpty()) {
                                drawBasalArea(
                                    filteredBasal,
                                    graphRect,
                                    ::xPos,
                                )
                            }

                            // 5. IoB overlay
                            if (config.showIoBOverlay && filteredIoB.isNotEmpty()) {
                                drawIoBArea(
                                    filteredIoB,
                                    graphRect,
                                    ::xPos,
                                )
                            }

                            // 6. Bolus markers with labels
                            if (config.showBolusMarkers && filteredBolus.isNotEmpty()) {
                                drawBolusMarkers(
                                    filteredBolus,
                                    graphRect,
                                    ::xPos,
                                    categoryLabels,
                                )
                            }

                            // 7. Glucose line segments
                            drawGlucoseLine(
                                readings,
                                graphRect,
                                ::xPos,
                                ::yPos,
                            )

                            // 8. Glucose dots
                            drawGlucoseDots(
                                readings,
                                graphRect,
                                ::xPos,
                                ::yPos,
                            )

                            // 9. Time axis labels
                            drawTimeAxis(
                                viewportInfo,
                                graphRect,
                                ::xPos,
                            )

                            // 10. Tooltip
                            tooltip?.let { drawTooltip(it) }
                        }
                    }

                    // Range info label
                    Text(
                        text = "${config.graphRangeHours}h  |  ${readings.size} readings",
                        style = MaterialTheme.typography.caption3,
                        color = Color(0xFF9CA3AF),
                        textAlign = TextAlign.Center,
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(16.dp),
                    )
                }
            }
        }
    }
}

// -- Viewport computation --

private data class ViewportInfo(
    val startMs: Long,
    val endMs: Long,
    val rangeMs: Long,
)

private fun computeViewport(
    panOffsetPx: Float,
    graphWidth: Float,
    viewportRangeMs: Long,
    dataStartMs: Long,
    nowMs: Long,
): ViewportInfo {
    if (graphWidth <= 0f) {
        return ViewportInfo(dataStartMs, nowMs, viewportRangeMs)
    }

    // Positive pan = drag right = scroll backward in time
    val panMs = (panOffsetPx / graphWidth * viewportRangeMs).toLong()

    // Default viewport end is now; panning right shifts it earlier.
    // Lower bound: ensure the viewport start doesn't go before the earliest data point.
    val minViewportEnd = dataStartMs + viewportRangeMs
    val viewportEnd = (nowMs - panMs).coerceIn(minViewportEnd.coerceAtMost(nowMs), nowMs)
    val viewportStart = viewportEnd - viewportRangeMs

    return ViewportInfo(
        startMs = viewportStart,
        endMs = viewportEnd,
        rangeMs = viewportRangeMs,
    )
}

// -- Drawing functions --

private fun DrawScope.drawRangeBand(
    low: Int,
    high: Int,
    graphRect: Rect,
    yPos: (Int) -> Float,
) {
    val lowY = yPos(low)
    val highY = yPos(high)
    drawRect(
        color = RANGE_BAND_COLOR,
        topLeft = Offset(graphRect.left, highY),
        size = Size(graphRect.width, lowY - highY),
    )
}

private fun DrawScope.drawThresholdLines(
    low: Int,
    high: Int,
    graphRect: Rect,
    yPos: (Int) -> Float,
) {
    val dashEffect = PathEffect.dashPathEffect(floatArrayOf(6f, 6f), 0f)
    val lineColor = Color(0x80FFFFFF)

    val lowY = yPos(low)
    val highY = yPos(high)

    // Low threshold line
    drawLine(
        color = lineColor,
        start = Offset(graphRect.left, lowY),
        end = Offset(graphRect.right, lowY),
        strokeWidth = THRESHOLD_LINE_WIDTH,
        pathEffect = dashEffect,
    )

    // High threshold line
    drawLine(
        color = lineColor,
        start = Offset(graphRect.left, highY),
        end = Offset(graphRect.right, highY),
        strokeWidth = THRESHOLD_LINE_WIDTH,
        pathEffect = dashEffect,
    )

    // Y-axis threshold labels
    val canvas = drawContext.canvas.nativeCanvas
    canvas.drawText(low.toString(), graphRect.left - 4f, lowY + 6f, GraphPaints.thresholdLabel)
    canvas.drawText(high.toString(), graphRect.left - 4f, highY + 6f, GraphPaints.thresholdLabel)
}

private fun DrawScope.drawModeBands(
    basalHistory: List<WatchDataRepository.BasalHistoryRecord>,
    graphRect: Rect,
    xPos: (Long) -> Float,
) {
    for (i in basalHistory.indices) {
        val record = basalHistory[i]
        if (record.activityMode == 0) continue
        val color = when (record.activityMode) {
            1 -> MODE_SLEEP_COLOR
            2 -> MODE_EXERCISE_COLOR
            else -> continue
        }
        val x1 = xPos(record.timestampMs).coerceIn(graphRect.left, graphRect.right)
        val x2 = if (i + 1 < basalHistory.size) {
            xPos(basalHistory[i + 1].timestampMs).coerceIn(graphRect.left, graphRect.right)
        } else {
            graphRect.right
        }
        if (x2 > x1) {
            drawRect(
                color = color,
                topLeft = Offset(x1, graphRect.top),
                size = Size(x2 - x1, graphRect.height),
            )
        }
    }
}

private fun DrawScope.drawGlucoseLine(
    readings: List<WatchDataRepository.CgmState>,
    graphRect: Rect,
    xPos: (Long) -> Float,
    yPos: (Int) -> Float,
) {
    for (i in 0 until readings.size - 1) {
        val r1 = readings[i]
        val r2 = readings[i + 1]
        val x1 = xPos(r1.timestampMs)
        val y1 = yPos(r1.mgDl)
        val x2 = xPos(r2.timestampMs)
        val y2 = yPos(r2.mgDl)

        // Skip segments entirely outside the visible graph area
        if (x2 < graphRect.left || x1 > graphRect.right) continue

        val color = Color(
            GlucoseDisplayUtils.bgColor(
                r1.mgDl, r1.low, r1.high, r1.urgentLow, r1.urgentHigh,
            ),
        )
        drawLine(
            color = color,
            start = Offset(x1, y1),
            end = Offset(x2, y2),
            strokeWidth = GLUCOSE_LINE_WIDTH,
        )
    }
}

private fun DrawScope.drawGlucoseDots(
    readings: List<WatchDataRepository.CgmState>,
    graphRect: Rect,
    xPos: (Long) -> Float,
    yPos: (Int) -> Float,
) {
    for (r in readings) {
        val x = xPos(r.timestampMs)
        // Skip dots outside visible area
        if (x < graphRect.left - GLUCOSE_DOT_RADIUS ||
            x > graphRect.right + GLUCOSE_DOT_RADIUS
        ) {
            continue
        }
        val y = yPos(r.mgDl)
        val color = Color(
            GlucoseDisplayUtils.bgColor(
                r.mgDl, r.low, r.high, r.urgentLow, r.urgentHigh,
            ),
        )
        drawCircle(
            color = color,
            radius = GLUCOSE_DOT_RADIUS,
            center = Offset(x, y),
        )
    }
}

private fun DrawScope.drawBolusMarkers(
    bolusHistory: List<WatchDataRepository.BolusHistoryRecord>,
    graphRect: Rect,
    xPos: (Long) -> Float,
    categoryLabels: Map<String, String>,
) {
    val markerCenterY = graphRect.top + BOLUS_MARKER_TOP_OFFSET + BOLUS_DIAMOND_HALF * 2

    for (record in bolusHistory) {
        val x = xPos(record.timestampMs)
        // Skip markers outside visible area
        if (x < graphRect.left - 20f || x > graphRect.right + 20f) continue

        val color = bolusColor(record.isAutomated, record.isCorrection, record.mealUnits)

        // Diamond shape
        val path = Path().apply {
            moveTo(x, markerCenterY - BOLUS_DIAMOND_HALF * 2) // top
            lineTo(x + BOLUS_DIAMOND_HALF, markerCenterY) // right
            lineTo(x, markerCenterY + BOLUS_DIAMOND_HALF * 2) // bottom
            lineTo(x - BOLUS_DIAMOND_HALF, markerCenterY) // left
            close()
        }
        drawPath(path = path, color = color, style = Fill)

        // Unit label above diamond
        val unitText = buildBolusLabel(record, categoryLabels)
        val clampedX = x.coerceIn(graphRect.left + 16f, graphRect.right - 16f)
        drawContext.canvas.nativeCanvas.drawText(
            unitText,
            clampedX,
            markerCenterY - BOLUS_DIAMOND_HALF * 2 - 3f,
            GraphPaints.bolusLabel,
        )
    }
}

private fun buildBolusLabel(
    record: WatchDataRepository.BolusHistoryRecord,
    categoryLabels: Map<String, String>,
): String {
    val unitsStr = if (record.units == record.units.toLong().toFloat()) {
        "${record.units.toLong()}u"
    } else {
        "%.1fu".format(record.units)
    }

    // Check for category label (e.g., "Auto Co." for auto-correction)
    val catLabel = categoryLabels[record.category]
    return if (record.isAutomated && record.isCorrection) {
        "$unitsStr ${catLabel ?: "Auto"}"
    } else if (catLabel != null) {
        "$unitsStr $catLabel"
    } else {
        unitsStr
    }
}

private fun bolusColor(
    isAutomated: Boolean,
    isCorrection: Boolean,
    mealUnits: Float,
): Color = when {
    isAutomated && isCorrection -> BOLUS_AUTO_CORRECTION
    isCorrection -> BOLUS_CORRECTION
    mealUnits > 0f -> BOLUS_MEAL
    else -> BOLUS_CORRECTION
}

private fun DrawScope.drawBasalArea(
    basalHistory: List<WatchDataRepository.BasalHistoryRecord>,
    graphRect: Rect,
    xPos: (Long) -> Float,
) {
    if (basalHistory.isEmpty()) return
    val maxRate = basalHistory.maxOf { it.rate }.coerceAtLeast(0.1f)

    for (i in basalHistory.indices) {
        val record = basalHistory[i]
        val color = basalColor(record.isAutomated, record.activityMode)
        val height = (record.rate / maxRate) * BASAL_AREA_HEIGHT
        val y = graphRect.bottom - height

        val x1 = xPos(record.timestampMs).coerceIn(graphRect.left, graphRect.right)
        val x2 = if (i + 1 < basalHistory.size) {
            xPos(basalHistory[i + 1].timestampMs).coerceIn(graphRect.left, graphRect.right)
        } else {
            graphRect.right
        }
        if (x2 > x1) {
            // Filled area
            drawRect(
                color = color.copy(alpha = 0.15f),
                topLeft = Offset(x1, y),
                size = Size(x2 - x1, graphRect.bottom - y),
            )
            // Top edge stroke
            drawLine(
                color = color.copy(alpha = 0.6f),
                start = Offset(x1, y),
                end = Offset(x2, y),
                strokeWidth = 1f,
            )
        }

        // Vertical step line between rate changes
        if (i > 0) {
            val prevHeight = (basalHistory[i - 1].rate / maxRate) * BASAL_AREA_HEIGHT
            val prevY = graphRect.bottom - prevHeight
            if (kotlin.math.abs(prevY - y) > 0.5f) {
                drawLine(
                    color = color.copy(alpha = 0.4f),
                    start = Offset(x1, prevY),
                    end = Offset(x1, y),
                    strokeWidth = 1f,
                )
            }
        }
    }
}

private fun basalColor(isAutomated: Boolean, activityMode: Int): Color = when {
    activityMode == 1 -> BASAL_SLEEP
    activityMode == 2 -> BASAL_EXERCISE
    isAutomated -> BASAL_AUTOMATED
    else -> BASAL_MANUAL
}

private fun DrawScope.drawIoBArea(
    iobHistory: List<WatchDataRepository.IoBHistoryRecord>,
    graphRect: Rect,
    xPos: (Long) -> Float,
) {
    if (iobHistory.isEmpty()) return
    val maxIoB = iobHistory.maxOf { it.iob }.coerceAtLeast(0.1f)

    val fillPath = Path()
    val linePath = Path()
    var started = false

    for (record in iobHistory) {
        val x = xPos(record.timestampMs).coerceIn(graphRect.left, graphRect.right)
        val height = (record.iob / maxIoB) * IOB_AREA_HEIGHT
        val y = graphRect.bottom - height

        if (!started) {
            fillPath.moveTo(x, graphRect.bottom)
            fillPath.lineTo(x, y)
            linePath.moveTo(x, y)
            started = true
        } else {
            fillPath.lineTo(x, y)
            linePath.lineTo(x, y)
        }
    }

    // Close fill path
    val lastX = xPos(iobHistory.last().timestampMs).coerceIn(graphRect.left, graphRect.right)
    fillPath.lineTo(lastX, graphRect.bottom)
    fillPath.close()

    drawPath(path = fillPath, color = IOB_FILL_COLOR)
    drawPath(path = linePath, color = IOB_LINE_COLOR, style = Stroke(width = 1.5f))
}

private fun DrawScope.drawTimeAxis(
    viewportInfo: ViewportInfo,
    graphRect: Rect,
    xPos: (Long) -> Float,
) {
    val tickColor = Color(0x40FFFFFF)

    // Determine hour mark interval based on viewport range
    val rangeHours = viewportInfo.rangeMs / 3_600_000L
    val intervalMs = when {
        rangeHours <= 1 -> 900_000L // 15-min marks for 1h range
        rangeHours <= 3 -> 3_600_000L // 1-hour marks
        else -> 7_200_000L // 2-hour marks for 6h
    }

    // Find the first interval mark after the viewport start, rounding in local time
    // so tick marks align to clean minute boundaries regardless of UTC offset.
    val intervalMinutes = (intervalMs / 60_000L).toInt()
    val cal = Calendar.getInstance()
    cal.timeInMillis = viewportInfo.startMs
    cal.set(Calendar.SECOND, 0)
    cal.set(Calendar.MILLISECOND, 0)
    val currentMinute = cal.get(Calendar.MINUTE)
    val nextMinute = ((currentMinute / intervalMinutes) + 1) * intervalMinutes
    cal.set(Calendar.MINUTE, 0)
    cal.add(Calendar.MINUTE, nextMinute)

    val canvas = drawContext.canvas.nativeCanvas
    while (cal.timeInMillis <= viewportInfo.endMs) {
        val x = xPos(cal.timeInMillis)
        if (x in graphRect.left..graphRect.right) {
            // Small tick mark
            drawLine(
                color = tickColor,
                start = Offset(x, graphRect.bottom),
                end = Offset(x, graphRect.bottom + 4f),
                strokeWidth = 1f,
            )
            // Time label
            canvas.drawText(
                timeAxisFormat.format(Date(cal.timeInMillis)),
                x,
                graphRect.bottom + 16f,
                GraphPaints.timeAxisLabel,
            )
        }
        cal.timeInMillis += intervalMs
    }
}

private fun DrawScope.drawTooltip(tooltip: TooltipData) {
    val textWidth = GraphPaints.tooltipText.measureText(tooltip.text)
    val padding = 10f
    val bubbleWidth = textWidth + padding * 2
    val bubbleHeight = 30f

    // Position above the dot, clamp to canvas bounds
    val maxLeft = (size.width - bubbleWidth).coerceAtLeast(0f)
    val bubbleX = (tooltip.x - bubbleWidth / 2f).coerceIn(0f, maxLeft)
    val bubbleY = (tooltip.y - bubbleHeight - 14f).coerceAtLeast(0f)

    drawRoundRect(
        color = Color(0xCC000000),
        topLeft = Offset(bubbleX, bubbleY),
        size = Size(bubbleWidth, bubbleHeight),
        cornerRadius = CornerRadius(8f, 8f),
    )

    drawContext.canvas.nativeCanvas.drawText(
        tooltip.text,
        bubbleX + bubbleWidth / 2f,
        bubbleY + bubbleHeight - 8f,
        GraphPaints.tooltipText,
    )
}

// -- Tap detection --

private fun findNearestReading(
    tapOffset: Offset,
    readings: List<WatchDataRepository.CgmState>,
    canvasWidth: Float,
    canvasHeight: Float,
    panOffsetPx: Float,
    viewportRangeMs: Long,
    dataStartMs: Long,
    nowMs: Long,
): TooltipData? {
    if (readings.isEmpty()) return null

    val graphLeft = GRAPH_PADDING
    val graphRight = canvasWidth - GRAPH_PADDING_RIGHT
    val graphTop = GRAPH_PADDING_TOP
    val graphBottom = canvasHeight - GRAPH_PADDING_BOTTOM
    val graphWidth = graphRight - graphLeft
    val graphHeight = graphBottom - graphTop

    val viewport = computeViewport(panOffsetPx, graphWidth, viewportRangeMs, dataStartMs, nowMs)

    val values = readings.map { it.mgDl }
    val low = readings.last().low
    val high = readings.last().high
    val minY = minOf(values.min(), low - 10).coerceAtLeast(Y_MIN_DEFAULT)
    val maxY = maxOf(values.max(), high + 10).coerceAtMost(Y_MAX_DEFAULT)
    val yRange = (maxY - minY).toFloat().coerceAtLeast(1f)

    fun xPos(timestampMs: Long): Float =
        graphLeft + ((timestampMs - viewport.startMs).toFloat() /
            viewport.rangeMs.toFloat()) * graphWidth

    fun yPos(mgDl: Int): Float =
        graphBottom - ((mgDl - minY).toFloat() / yRange) * graphHeight

    var nearestIdx = -1
    var nearestDist = Float.MAX_VALUE

    for (i in readings.indices) {
        val r = readings[i]
        val dotX = xPos(r.timestampMs)
        val dotY = yPos(r.mgDl)
        val dx = tapOffset.x - dotX
        val dy = tapOffset.y - dotY
        val dist = dx * dx + dy * dy
        if (dist < nearestDist) {
            nearestDist = dist
            nearestIdx = i
        }
    }

    if (nearestIdx < 0 || nearestDist > TAP_RADIUS_SQ) return null

    val r = readings[nearestIdx]
    val dotX = xPos(r.timestampMs)
    val dotY = yPos(r.mgDl)
    val timeText = tooltipTimeFormat.format(Date(r.timestampMs))
    return TooltipData(
        text = "${r.mgDl} mg/dL  $timeText",
        x = dotX,
        y = dotY,
    )
}
