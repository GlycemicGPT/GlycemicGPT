package com.glycemicgpt.weardevice.presentation

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.Canvas
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
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Scaffold
import androidx.wear.compose.material.Text
import androidx.wear.compose.material.TimeText
import com.glycemicgpt.weardevice.complications.WatchGraphRenderer
import com.glycemicgpt.weardevice.data.WatchDataRepository
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

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

@Composable
private fun GraphDetailScreen() {
    val config by WatchDataRepository.watchFaceConfig.collectAsState()
    val cgmHistory by WatchDataRepository.cgmHistory.collectAsState()
    val basalHistory by WatchDataRepository.basalHistory.collectAsState()
    val bolusHistory by WatchDataRepository.bolusHistory.collectAsState()
    val iobHistory by WatchDataRepository.iobHistory.collectAsState()

    val rangeMs = config.graphRangeHours * 3_600_000L
    val cutoff = remember(cgmHistory, config.graphRangeHours) {
        System.currentTimeMillis() - rangeMs
    }
    val readings = remember(cgmHistory, cutoff) {
        cgmHistory.filter { it.timestampMs >= cutoff }.sortedBy { it.timestampMs }
    }

    var tooltip by remember { mutableStateOf<TooltipData?>(null) }

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
                    // Render the full-screen graph using the existing renderer
                    val graphConfig = WatchGraphRenderer.GraphConfig(
                        showBasalOverlay = config.showBasalOverlay,
                        showBolusMarkers = config.showBolusMarkers,
                        showIoBOverlay = config.showIoBOverlay,
                        showModeBands = config.showModeBands,
                    )
                    val low = readings.last().low
                    val high = readings.last().high
                    val filteredBasal = remember(basalHistory, cutoff) {
                        basalHistory.filter { it.timestampMs >= cutoff }
                    }
                    val filteredBolus = remember(bolusHistory, cutoff) {
                        bolusHistory.filter { it.timestampMs >= cutoff }
                    }
                    val filteredIoB = remember(iobHistory, cutoff) {
                        iobHistory.filter { it.timestampMs >= cutoff }
                    }

                    val bitmap = remember(
                        readings,
                        filteredBasal,
                        filteredBolus,
                        filteredIoB,
                        low,
                        high,
                        graphConfig,
                    ) {
                        WatchGraphRenderer.render(
                            cgmReadings = readings,
                            basalHistory = filteredBasal,
                            bolusHistory = filteredBolus,
                            iobHistory = filteredIoB,
                            low = low,
                            high = high,
                            config = graphConfig,
                        )
                    }

                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .weight(1f),
                    ) {
                        Canvas(
                            modifier = Modifier
                                .fillMaxSize()
                                .pointerInput(readings) {
                                    detectTapGestures { offset ->
                                        tooltip = findNearestReading(
                                            offset = offset,
                                            readings = readings,
                                            canvasWidth = size.width.toFloat(),
                                            canvasHeight = size.height.toFloat(),
                                        )
                                    }
                                },
                        ) {
                            drawImage(bitmap, size)
                            tooltip?.let { drawTooltip(it) }
                        }
                    }

                    // Range label
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

private fun DrawScope.drawImage(
    bitmap: android.graphics.Bitmap,
    size: androidx.compose.ui.geometry.Size,
) {
    val canvas = drawContext.canvas.nativeCanvas
    val srcRect = android.graphics.Rect(
        0, 0, bitmap.width, bitmap.height,
    )
    val dstRect = android.graphics.RectF(
        0f, 0f, size.width, size.height,
    )
    canvas.drawBitmap(bitmap, srcRect, dstRect, null)
}

private fun DrawScope.drawTooltip(tooltip: TooltipData) {
    val textPaint = android.graphics.Paint().apply {
        color = android.graphics.Color.WHITE
        textSize = 24f
        isAntiAlias = true
        textAlign = android.graphics.Paint.Align.CENTER
        isFakeBoldText = true
    }
    val bgPaint = android.graphics.Paint().apply {
        color = 0xCC000000.toInt()
        isAntiAlias = true
    }

    val textWidth = textPaint.measureText(tooltip.text)
    val padding = 8f
    val bubbleWidth = minOf(textWidth + padding * 2, size.width)
    val bubbleHeight = 32f

    // Position above the dot, clamp to canvas bounds
    val maxLeft = (size.width - bubbleWidth).coerceAtLeast(0f)
    val bubbleX = (tooltip.x - bubbleWidth / 2f).coerceIn(0f, maxLeft)
    val bubbleY = (tooltip.y - bubbleHeight - 12f).coerceAtLeast(0f)

    val canvas = drawContext.canvas.nativeCanvas
    canvas.drawRoundRect(
        bubbleX,
        bubbleY,
        bubbleX + bubbleWidth,
        bubbleY + bubbleHeight,
        8f,
        8f,
        bgPaint,
    )
    canvas.drawText(
        tooltip.text,
        bubbleX + bubbleWidth / 2f,
        bubbleY + bubbleHeight - 8f,
        textPaint,
    )
}

private fun findNearestReading(
    offset: Offset,
    readings: List<WatchDataRepository.CgmState>,
    canvasWidth: Float,
    canvasHeight: Float,
): TooltipData? {
    if (readings.isEmpty()) return null

    val padding = 4f
    val graphLeft = padding
    val graphRight = canvasWidth - padding
    val graphTop = padding
    val graphBottom = canvasHeight - padding
    val graphWidth = graphRight - graphLeft
    val graphHeight = graphBottom - graphTop

    val values = readings.map { it.mgDl }
    val low = readings.last().low
    val high = readings.last().high
    val minY = minOf(values.min(), low - 10).coerceAtLeast(20)
    val maxY = maxOf(values.max(), high + 10).coerceAtMost(500)
    val yRange = (maxY - minY).toFloat().coerceAtLeast(1f)

    val minX = readings.first().timestampMs
    val maxX = readings.last().timestampMs
    val xRange = (maxX - minX).toFloat().coerceAtLeast(1f)

    var nearestIdx = -1
    var nearestDist = Float.MAX_VALUE

    for (i in readings.indices) {
        val r = readings[i]
        val dotX = graphLeft + ((r.timestampMs - minX) / xRange) * graphWidth
        val dotY = graphBottom - ((r.mgDl - minY) / yRange) * graphHeight
        val dx = offset.x - dotX
        val dy = offset.y - dotY
        val dist = dx * dx + dy * dy
        if (dist < nearestDist) {
            nearestDist = dist
            nearestIdx = i
        }
    }

    // Only show tooltip if tap is within reasonable distance
    if (nearestIdx < 0 || nearestDist > TAP_RADIUS_SQ) return null

    val r = readings[nearestIdx]
    val dotX = graphLeft + ((r.timestampMs - minX) / xRange) * graphWidth
    val dotY = graphBottom - ((r.mgDl - minY) / yRange) * graphHeight
    val timeText = SimpleDateFormat("h:mm a", Locale.getDefault()).format(Date(r.timestampMs))
    return TooltipData(
        text = "${r.mgDl} mg/dL  $timeText",
        x = dotX,
        y = dotY,
    )
}

private const val MIN_READINGS = 3
/** Squared distance threshold for tap detection (in pixels). */
private const val TAP_RADIUS_SQ = 2500f // 50px radius
