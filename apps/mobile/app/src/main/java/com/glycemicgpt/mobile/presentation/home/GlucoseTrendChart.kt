package com.glycemicgpt.mobile.presentation.home

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Fill
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.ControlIqMode
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.presentation.theme.GlucoseColors
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

enum class ChartPeriod(val label: String, val hours: Long) {
    THREE_HOURS("3H", 3),
    SIX_HOURS("6H", 6),
    TWELVE_HOURS("12H", 12),
    TWENTY_FOUR_HOURS("24H", 24),
}

private object ChartColors {
    val BasalAuto = Color(0xFF00BCD4)     // Teal -- auto basal (algorithm adjusted)
    val BasalProfile = Color(0xFF78909C)  // Blue-grey -- profile/manual basal
    val BasalSleep = Color(0xFF7E57C2)    // Purple -- sleep mode
    val BasalExercise = Color(0xFFFF9800) // Orange -- exercise mode
    val Correction = Color(0xFFE91E63)    // Pink -- auto correction (pump-initiated)
    val ManualCorrection = Color(0xFFFF5722)  // Deep orange -- manual correction (user-initiated)
    val Bolus = Color(0xFF7C4DFF)         // Deep purple -- meal/standard bolus
}

@Composable
fun GlucoseTrendChart(
    readings: List<CgmReading>,
    iobReadings: List<IoBReading>,
    basalReadings: List<BasalReading>,
    bolusEvents: List<BolusEvent>,
    selectedPeriod: ChartPeriod,
    onPeriodSelected: (ChartPeriod) -> Unit,
    thresholds: GlucoseThresholds = GlucoseThresholds(),
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface,
        ),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
        ) {
            // Period selector
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
            ) {
                ChartPeriod.entries.forEach { period ->
                    FilterChip(
                        selected = period == selectedPeriod,
                        onClick = { onPeriodSelected(period) },
                        label = {
                            Text(
                                text = period.label,
                                style = MaterialTheme.typography.labelMedium,
                            )
                        },
                        modifier = Modifier
                            .padding(horizontal = 4.dp)
                            .testTag("period_chip_${period.label}"),
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor = MaterialTheme.colorScheme.primary,
                            selectedLabelColor = MaterialTheme.colorScheme.onPrimary,
                        ),
                        shape = RoundedCornerShape(8.dp),
                    )
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            if (readings.isEmpty()) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(280.dp)
                        .testTag("chart_empty_state"),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = "No glucose readings yet",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            } else {
                val textMeasurer = rememberTextMeasurer()
                val axisLabelColor = MaterialTheme.colorScheme.onSurfaceVariant
                val gridColor = MaterialTheme.colorScheme.outline.copy(alpha = 0.3f)
                val iobColor = MaterialTheme.colorScheme.primary
                val nowMs = remember(readings, iobReadings, basalReadings, bolusEvents, selectedPeriod) {
                    System.currentTimeMillis()
                }
                val iobSuffix = if (iobReadings.isNotEmpty()) ", with insulin on board overlay" else ""
                val basalSuffix = if (basalReadings.isNotEmpty()) ", with basal rate overlay" else ""
                val bolusSuffix = if (bolusEvents.isNotEmpty()) ", with ${bolusEvents.size} bolus markers" else ""
                val a11yLabel = "Glucose trend chart showing ${readings.size} readings " +
                    "over the last ${selectedPeriod.label}" + iobSuffix + basalSuffix + bolusSuffix

                Canvas(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(280.dp)
                        .testTag("glucose_chart")
                        .semantics { contentDescription = a11yLabel },
                ) {
                    drawGlucoseChart(
                        readings = readings,
                        iobReadings = iobReadings,
                        basalReadings = basalReadings,
                        bolusEvents = bolusEvents,
                        period = selectedPeriod,
                        nowMs = nowMs,
                        textMeasurer = textMeasurer,
                        axisLabelColor = axisLabelColor,
                        gridColor = gridColor,
                        iobColor = iobColor,
                        thresholds = thresholds,
                    )
                }

                // Legend row
                Spacer(modifier = Modifier.height(6.dp))
                val basalModesPresent = remember(basalReadings) {
                    buildSet {
                        for (r in basalReadings) {
                            when {
                                r.controlIqMode == ControlIqMode.SLEEP -> add("sleep")
                                r.controlIqMode == ControlIqMode.EXERCISE -> add("exercise")
                                r.isAutomated -> add("auto")
                                else -> add("profile")
                            }
                        }
                    }
                }
                val bolusTypesPresent = remember(bolusEvents) {
                    buildSet {
                        for (b in bolusEvents) {
                            when {
                                b.isAutomated -> add("auto_correction")
                                b.isCorrection -> add("manual_correction")
                                else -> add("meal_bolus")
                            }
                        }
                    }
                }
                ChartLegend(
                    hasIob = iobReadings.isNotEmpty(),
                    basalModesPresent = basalModesPresent,
                    bolusTypesPresent = bolusTypesPresent,
                    iobColor = iobColor,
                )
            }
        }
    }
}

@Composable
private fun ChartLegend(
    hasIob: Boolean,
    basalModesPresent: Set<String>,
    bolusTypesPresent: Set<String>,
    iobColor: Color,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if ("auto" in basalModesPresent) LegendItem(color = ChartColors.BasalAuto, label = "Auto")
        if ("profile" in basalModesPresent) LegendItem(color = ChartColors.BasalProfile, label = "Profile")
        if ("sleep" in basalModesPresent) LegendItem(color = ChartColors.BasalSleep, label = "Sleep")
        if ("exercise" in basalModesPresent) LegendItem(color = ChartColors.BasalExercise, label = "Exercise")
        if ("auto_correction" in bolusTypesPresent) LegendItem(color = ChartColors.Correction, label = "Auto Correction")
        if ("manual_correction" in bolusTypesPresent) LegendItem(color = ChartColors.ManualCorrection, label = "Manual Correction")
        if ("meal_bolus" in bolusTypesPresent) LegendItem(color = ChartColors.Bolus, label = "Meal Bolus")
        if (hasIob) LegendItem(color = iobColor.copy(alpha = 0.7f), label = "IoB")
    }
}

@Composable
private fun LegendItem(color: Color, label: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Canvas(modifier = Modifier.size(8.dp)) {
            drawCircle(color = color, radius = size.minDimension / 2f)
        }
        Spacer(modifier = Modifier.width(3.dp))
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = color,
        )
    }
}

@Suppress("LongMethod")
private fun DrawScope.drawGlucoseChart(
    readings: List<CgmReading>,
    iobReadings: List<IoBReading>,
    basalReadings: List<BasalReading>,
    bolusEvents: List<BolusEvent>,
    period: ChartPeriod,
    nowMs: Long,
    textMeasurer: TextMeasurer,
    axisLabelColor: Color,
    gridColor: Color,
    iobColor: Color,
    thresholds: GlucoseThresholds = GlucoseThresholds(),
) {
    val leftPadding = 36.dp.toPx()
    val bottomPadding = 24.dp.toPx()
    val topPadding = 8.dp.toPx()
    val rightPadding = if (iobReadings.isNotEmpty()) 32.dp.toPx() else 8.dp.toPx()

    val chartWidth = size.width - leftPadding - rightPadding
    val chartHeight = size.height - topPadding - bottomPadding

    // Y-axis range: 40 to 300 mg/dL
    val yMin = 40f
    val yMax = 300f
    val yRange = yMax - yMin

    // X-axis range
    val periodMs = period.hours * 3600_000L
    val xMin = nowMs - periodMs
    val xMax = nowMs

    // Target range band (dynamic thresholds)
    val bandTopY = topPadding + chartHeight * (1f - (thresholds.high - yMin) / yRange)
    val bandBottomY = topPadding + chartHeight * (1f - (thresholds.low - yMin) / yRange)
    drawRect(
        color = GlucoseColors.InRange.copy(alpha = 0.08f),
        topLeft = Offset(leftPadding, bandTopY),
        size = Size(chartWidth, bandBottomY - bandTopY),
    )

    // Grid lines at threshold boundaries
    val gridValues = listOf(thresholds.low.toFloat(), thresholds.high.toFloat(), thresholds.urgentHigh.toFloat())
    val dashedEffect = PathEffect.dashPathEffect(floatArrayOf(8f, 8f))
    for (value in gridValues) {
        val y = topPadding + chartHeight * (1f - (value - yMin) / yRange)
        drawLine(
            color = gridColor,
            start = Offset(leftPadding, y),
            end = Offset(leftPadding + chartWidth, y),
            pathEffect = dashedEffect,
            strokeWidth = 1f,
        )
    }

    // Y-axis labels (left: glucose)
    val yLabelValues = listOf(thresholds.low, thresholds.high, thresholds.urgentHigh)
    val labelStyle = TextStyle(fontSize = 10.sp, color = axisLabelColor)
    for (value in yLabelValues) {
        val y = topPadding + chartHeight * (1f - (value - yMin) / yRange)
        val textResult = textMeasurer.measure("$value", labelStyle)
        drawText(
            textResult,
            topLeft = Offset(
                leftPadding - textResult.size.width - 3.dp.toPx(),
                y - textResult.size.height / 2f,
            ),
        )
    }

    // X-axis time labels
    val timeFormatter = DateTimeFormatter.ofPattern(
        if (period.hours <= 6) "h:mm" else "ha",
    ).withZone(ZoneId.systemDefault())

    val tickCount = when (period) {
        ChartPeriod.THREE_HOURS -> 3
        ChartPeriod.SIX_HOURS -> 3
        ChartPeriod.TWELVE_HOURS -> 4
        ChartPeriod.TWENTY_FOUR_HOURS -> 4
    }

    for (i in 0..tickCount) {
        val tickMs = xMin + (xMax - xMin) * i.toLong() / tickCount.toLong()
        val x = leftPadding + chartWidth * i.toFloat() / tickCount.toFloat()
        val label = timeFormatter.format(Instant.ofEpochMilli(tickMs))
        val textResult = textMeasurer.measure(label, labelStyle)
        drawText(
            textResult,
            topLeft = Offset(
                x - textResult.size.width / 2f,
                size.height - bottomPadding + 4.dp.toPx(),
            ),
        )
    }

    // -- Mode overlay bands (full-height colored bands for sleep/exercise modes) --
    drawModeOverlay(
        basalReadings = basalReadings,
        xMin = xMin,
        xMax = xMax,
        leftPadding = leftPadding,
        topPadding = topPadding,
        chartWidth = chartWidth,
        chartHeight = chartHeight,
    )

    // -- Basal rate stepped area (drawn first, behind everything) ----------------
    drawBasalOverlay(
        basalReadings = basalReadings,
        xMin = xMin,
        xMax = xMax,
        leftPadding = leftPadding,
        topPadding = topPadding,
        chartWidth = chartWidth,
        chartHeight = chartHeight,
    )

    // -- IoB overlay (filled area + line on secondary axis) ----------------------
    drawIoBOverlay(
        iobReadings = iobReadings,
        xMin = xMin,
        xMax = xMax,
        leftPadding = leftPadding,
        topPadding = topPadding,
        chartWidth = chartWidth,
        chartHeight = chartHeight,
        iobColor = iobColor,
        textMeasurer = textMeasurer,
    )

    // -- Bolus event markers -----------------------------------------------------
    drawBolusMarkers(
        bolusEvents = bolusEvents,
        xMin = xMin,
        xMax = xMax,
        leftPadding = leftPadding,
        topPadding = topPadding,
        chartWidth = chartWidth,
        chartHeight = chartHeight,
        textMeasurer = textMeasurer,
    )

    // -- Glucose data points (drawn last so they're on top) ----------------------
    val dotRadius = 3.dp.toPx()
    for (reading in readings) {
        val ts = reading.timestamp.toEpochMilli()
        if (ts < xMin || ts > xMax) continue

        val x = leftPadding + chartWidth * (ts - xMin).toFloat() / (xMax - xMin).toFloat()
        val clampedValue = reading.glucoseMgDl.coerceIn(yMin.toInt(), yMax.toInt())
        val y = topPadding + chartHeight * (1f - (clampedValue - yMin) / yRange)
        val color = glucoseColor(reading.glucoseMgDl, thresholds)

        drawCircle(
            color = color,
            radius = dotRadius,
            center = Offset(x, y),
        )
    }
}

private fun DrawScope.drawBasalOverlay(
    basalReadings: List<BasalReading>,
    xMin: Long,
    xMax: Long,
    leftPadding: Float,
    topPadding: Float,
    chartWidth: Float,
    chartHeight: Float,
) {
    if (basalReadings.isEmpty()) return

    val maxRate = basalReadings.maxOf { it.rate }.coerceIn(0.1f, 15.0f)
    // Basal uses the bottom 25% of chart height
    val basalHeight = chartHeight * 0.25f
    val basalBottom = topPadding + chartHeight

    for (i in basalReadings.indices) {
        val reading = basalReadings[i]
        val ts = reading.timestamp.toEpochMilli()
        if (ts > xMax) continue

        // Each segment extends from this reading to the next (or to xMax)
        val nextTs = if (i + 1 < basalReadings.size) {
            basalReadings[i + 1].timestamp.toEpochMilli().coerceAtMost(xMax)
        } else {
            xMax
        }
        if (nextTs < xMin) continue

        val startMs = ts.coerceAtLeast(xMin)
        val x1 = leftPadding + chartWidth * (startMs - xMin).toFloat() / (xMax - xMin).toFloat()
        val x2 = leftPadding + chartWidth * (nextTs - xMin).toFloat() / (xMax - xMin).toFloat()
        val segHeight = basalHeight * (reading.rate / maxRate)
        val y = basalBottom - segHeight

        val color = when {
            reading.controlIqMode == ControlIqMode.SLEEP -> ChartColors.BasalSleep
            reading.controlIqMode == ControlIqMode.EXERCISE -> ChartColors.BasalExercise
            reading.isAutomated -> ChartColors.BasalAuto
            else -> ChartColors.BasalProfile
        }

        // Filled rectangle for this basal segment
        drawRect(
            color = color.copy(alpha = 0.15f),
            topLeft = Offset(x1, y),
            size = Size(x2 - x1, segHeight),
        )
        // Top edge line
        drawLine(
            color = color.copy(alpha = 0.6f),
            start = Offset(x1, y),
            end = Offset(x2, y),
            strokeWidth = 1.5.dp.toPx(),
        )
        // Vertical step lines between segments
        if (i > 0) {
            val prevReading = basalReadings[i - 1]
            val prevSegHeight = basalHeight * (prevReading.rate / maxRate)
            val prevY = basalBottom - prevSegHeight
            if (ts >= xMin) {
                drawLine(
                    color = color.copy(alpha = 0.4f),
                    start = Offset(x1, prevY),
                    end = Offset(x1, y),
                    strokeWidth = 1.dp.toPx(),
                )
            }
        }
    }
}

private fun DrawScope.drawModeOverlay(
    basalReadings: List<BasalReading>,
    xMin: Long,
    xMax: Long,
    leftPadding: Float,
    topPadding: Float,
    chartWidth: Float,
    chartHeight: Float,
) {
    if (basalReadings.isEmpty()) return

    for (i in basalReadings.indices) {
        val reading = basalReadings[i]
        val mode = reading.controlIqMode
        // Only draw overlays for sleep and exercise/activity modes
        if (mode != ControlIqMode.SLEEP && mode != ControlIqMode.EXERCISE) continue

        val ts = reading.timestamp.toEpochMilli()
        if (ts > xMax) continue

        val nextTs = if (i + 1 < basalReadings.size) {
            basalReadings[i + 1].timestamp.toEpochMilli().coerceAtMost(xMax)
        } else {
            xMax
        }
        if (nextTs < xMin) continue

        val startMs = ts.coerceAtLeast(xMin)
        val x1 = leftPadding + chartWidth * (startMs - xMin).toFloat() / (xMax - xMin).toFloat()
        val x2 = leftPadding + chartWidth * (nextTs - xMin).toFloat() / (xMax - xMin).toFloat()

        val color = if (mode == ControlIqMode.SLEEP) {
            ChartColors.BasalSleep
        } else {
            ChartColors.BasalExercise
        }

        // Full-height background band
        drawRect(
            color = color.copy(alpha = 0.06f),
            topLeft = Offset(x1, topPadding),
            size = Size(x2 - x1, chartHeight),
        )
    }
}

private fun DrawScope.drawIoBOverlay(
    iobReadings: List<IoBReading>,
    xMin: Long,
    xMax: Long,
    leftPadding: Float,
    topPadding: Float,
    chartWidth: Float,
    chartHeight: Float,
    iobColor: Color,
    textMeasurer: TextMeasurer,
) {
    if (iobReadings.size < 2) return

    val maxIob = iobReadings.maxOf { it.iob }.coerceAtLeast(1f)
    val iobAreaPath = Path()
    val iobLinePath = Path()
    var started = false
    var lastInRangeX = 0f

    for (reading in iobReadings) {
        val ts = reading.timestamp.toEpochMilli()
        if (ts < xMin || ts > xMax) continue

        val x = leftPadding + chartWidth * (ts - xMin).toFloat() / (xMax - xMin).toFloat()
        val y = topPadding + chartHeight * (1f - reading.iob / maxIob)
        lastInRangeX = x

        if (!started) {
            iobAreaPath.moveTo(x, topPadding + chartHeight)
            iobAreaPath.lineTo(x, y)
            iobLinePath.moveTo(x, y)
            started = true
        } else {
            iobAreaPath.lineTo(x, y)
            iobLinePath.lineTo(x, y)
        }
    }

    if (started) {
        iobAreaPath.lineTo(lastInRangeX, topPadding + chartHeight)
        iobAreaPath.close()

        drawPath(iobAreaPath, iobColor.copy(alpha = 0.06f), style = Fill)
        drawPath(iobLinePath, iobColor.copy(alpha = 0.4f), style = Stroke(width = 1.5.dp.toPx()))

        // Right Y-axis labels for IoB
        val iobLabelStyle = TextStyle(fontSize = 9.sp, color = iobColor.copy(alpha = 0.6f))
        val topLabel = textMeasurer.measure("%.1fu".format(maxIob), iobLabelStyle)
        drawText(topLabel, topLeft = Offset(leftPadding + chartWidth + 3.dp.toPx(), topPadding))
        val bottomLabel = textMeasurer.measure("0u", iobLabelStyle)
        drawText(
            bottomLabel,
            topLeft = Offset(
                leftPadding + chartWidth + 3.dp.toPx(),
                topPadding + chartHeight - bottomLabel.size.height,
            ),
        )
    }
}

private fun DrawScope.drawBolusMarkers(
    bolusEvents: List<BolusEvent>,
    xMin: Long,
    xMax: Long,
    leftPadding: Float,
    topPadding: Float,
    chartWidth: Float,
    chartHeight: Float,
    textMeasurer: TextMeasurer,
) {
    if (bolusEvents.isEmpty()) return

    val markerRadius = 4.dp.toPx()
    val labelStyle = TextStyle(fontSize = 8.sp)
    val minSpacing = 20.dp.toPx()
    val staggerStep = 18.dp.toPx()
    val baseMarkerY = topPadding + 16.dp.toPx()
    // Cap stagger levels so clustered boluses don't overflow into glucose area
    val maxStaggerLevels = ((chartHeight * 0.25f) / staggerStep).toInt().coerceAtLeast(1)
    var prevX = Float.NEGATIVE_INFINITY
    var staggerLevel = 0

    for (event in bolusEvents) {
        val ts = event.timestamp.toEpochMilli()
        if (ts < xMin || ts > xMax) continue

        val x = leftPadding + chartWidth * (ts - xMin).toFloat() / (xMax - xMin).toFloat()

        // Stagger markers that are too close together (capped to avoid glucose overlap)
        if (x - prevX < minSpacing) {
            staggerLevel = (staggerLevel + 1).coerceAtMost(maxStaggerLevels)
        } else {
            staggerLevel = 0
        }
        prevX = x

        val color = when {
            event.isAutomated -> ChartColors.Correction        // Pink: pump auto-correction
            event.isCorrection -> ChartColors.ManualCorrection  // Deep orange: user correction
            else -> ChartColors.Bolus                           // Purple: meal bolus
        }

        val markerY = baseMarkerY + staggerLevel * staggerStep

        // Vertical line from marker down into the chart
        drawLine(
            color = color.copy(alpha = 0.3f),
            start = Offset(x, markerY + markerRadius),
            end = Offset(x, topPadding + chartHeight),
            strokeWidth = 1.dp.toPx(),
            pathEffect = PathEffect.dashPathEffect(floatArrayOf(4f, 4f)),
        )

        // Diamond marker
        val diamond = Path().apply {
            moveTo(x, markerY - markerRadius)          // top
            lineTo(x + markerRadius, markerY)           // right
            lineTo(x, markerY + markerRadius)           // bottom
            lineTo(x - markerRadius, markerY)           // left
            close()
        }
        drawPath(diamond, color, style = Fill)

        // Units label above the marker, clamped to canvas bounds
        val unitsLabel = textMeasurer.measure(
            "%.1fu".format(event.units),
            labelStyle.copy(color = color),
        )
        val labelY = (markerY - markerRadius - unitsLabel.size.height - 2.dp.toPx())
            .coerceAtLeast(0f)
        drawText(
            unitsLabel,
            topLeft = Offset(
                x - unitsLabel.size.width / 2f,
                labelY,
            ),
        )

        // "AUTO" tag above units label for automated corrections
        if (event.isAutomated) {
            val autoTagStyle = TextStyle(fontSize = 7.sp, color = color.copy(alpha = 0.8f))
            val autoTag = textMeasurer.measure("AUTO", autoTagStyle)
            val autoTagY = (labelY - autoTag.size.height - 1.dp.toPx()).coerceAtLeast(0f)
            drawText(
                autoTag,
                topLeft = Offset(x - autoTag.size.width / 2f, autoTagY),
            )
        }
    }
}
