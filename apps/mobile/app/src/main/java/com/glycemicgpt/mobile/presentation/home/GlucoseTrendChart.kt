package com.glycemicgpt.mobile.presentation.home

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.OpenInFull
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
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
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.glycemicgpt.mobile.domain.compute.DashboardComputations
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.BolusType
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.PumpActivityMode
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
    THREE_DAYS("3D", 72),
    SEVEN_DAYS("7D", 168),
    FOURTEEN_DAYS("14D", 336),
    THIRTY_DAYS("30D", 720),
}

private val HOME_PERIODS = ChartPeriod.entries.take(4)

private data class ChartTooltip(
    val reading: CgmReading,
    val canvasX: Float,
    val canvasY: Float,
)

/** Minimum visible span when zoomed in (15 minutes). */
private const val MIN_VISIBLE_MS = 15L * 60_000L

/** Y-axis range constants (mg/dL) shared between draw and tap-hit logic. */
private const val CHART_Y_MIN = 40f
private const val CHART_Y_MAX = 300f

/** Formatter for tooltip time display (hoisted to avoid per-recomposition allocation). */
private val TOOLTIP_TIME_FORMAT: DateTimeFormatter =
    DateTimeFormatter.ofPattern("h:mm a").withZone(ZoneId.systemDefault())

private object ChartColors {
    val BasalAutomated = Color(0xFF00BCD4)  // Teal -- automated basal (algorithm adjusted)
    val BasalManual = Color(0xFF78909C)     // Blue-grey -- manual basal
    val BasalSleep = Color(0xFF7E57C2)      // Purple -- sleep mode
    val BasalExercise = Color(0xFFFF9800)   // Orange -- exercise mode
    val Correction = Color(0xFFE91E63)    // Pink -- auto correction (pump-initiated)
    val ManualCorrection = Color(0xFFFF5722)  // Deep orange -- manual correction (user-initiated)
    val Bolus = Color(0xFF7C4DFF)         // Deep purple -- meal/standard bolus
    val MealWithCorrection = Color(0xFFAB47BC) // Medium purple -- meal + correction combo
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
    onClick: (() -> Unit)? = null,
    isDetailMode: Boolean = false,
    showPeriodSelector: Boolean = true,
    modifier: Modifier = Modifier,
) {
    val content: @Composable (Modifier) -> Unit = { innerModifier ->
        GlucoseTrendChartContent(
            readings = readings,
            iobReadings = iobReadings,
            basalReadings = basalReadings,
            bolusEvents = bolusEvents,
            selectedPeriod = selectedPeriod,
            onPeriodSelected = onPeriodSelected,
            thresholds = thresholds,
            onClick = onClick,
            isDetailMode = isDetailMode,
            showPeriodSelector = showPeriodSelector,
            modifier = innerModifier,
        )
    }

    if (isDetailMode) {
        // Detail mode: no Card wrapper, fill available space
        content(modifier)
    } else {
        Card(
            modifier = modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surface,
            ),
        ) {
            content(Modifier.padding(16.dp))
        }
    }
}

@Composable
private fun GlucoseTrendChartContent(
    readings: List<CgmReading>,
    iobReadings: List<IoBReading>,
    basalReadings: List<BasalReading>,
    bolusEvents: List<BolusEvent>,
    selectedPeriod: ChartPeriod,
    onPeriodSelected: (ChartPeriod) -> Unit,
    thresholds: GlucoseThresholds,
    onClick: (() -> Unit)?,
    isDetailMode: Boolean,
    showPeriodSelector: Boolean = true,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier) {
        // Header row with title and expand button (shown on home screen only)
        if (onClick != null) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "Glucose Trend",
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                IconButton(
                    onClick = onClick,
                    modifier = Modifier
                        .size(48.dp)
                        .testTag("expand_chart_detail"),
                ) {
                    Icon(
                        imageVector = Icons.Default.OpenInFull,
                        contentDescription = "Expand chart detail",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(20.dp),
                    )
                }
            }

            Spacer(modifier = Modifier.height(8.dp))
        }

        // Period selector (hidden when managed externally, e.g. detail screen)
        if (showPeriodSelector) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
            ) {
                HOME_PERIODS.forEach { period ->
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
        }

        if (readings.isEmpty()) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .then(
                        if (isDetailMode) Modifier.weight(1f) else Modifier.height(280.dp),
                    )
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
            val fullPeriodMs = selectedPeriod.hours * 3600_000L
            val fullStartMs = nowMs - fullPeriodMs

            // -- Zoom / pan state (detail mode only) --
            var viewportSpan by remember(selectedPeriod) { mutableLongStateOf(fullPeriodMs) }
            var viewportCenter by remember(selectedPeriod) {
                mutableLongStateOf(nowMs - fullPeriodMs / 2)
            }

            val visibleStartMs = (viewportCenter - viewportSpan / 2).coerceAtLeast(fullStartMs)
            val visibleEndMs = (viewportCenter + viewportSpan / 2).coerceAtMost(nowMs)

            // Pass the visible window (zoom-aware) to the draw function
            val drawXMin = if (isDetailMode) visibleStartMs else (nowMs - fullPeriodMs)
            val drawXMax = if (isDetailMode) visibleEndMs else nowMs

            // -- Tooltip state (detail mode only) --
            var tooltip by remember { mutableStateOf<ChartTooltip?>(null) }

            // Chart layout params for hit-testing (captured during draw)
            var chartLeftPadding by remember { mutableFloatStateOf(0f) }
            var chartWidth by remember { mutableFloatStateOf(0f) }
            var chartTopPadding by remember { mutableFloatStateOf(0f) }
            var chartHeight by remember { mutableFloatStateOf(0f) }

            val iobSuffix = if (iobReadings.isNotEmpty()) ", with insulin on board overlay" else ""
            val basalSuffix = if (basalReadings.isNotEmpty()) ", with basal rate overlay" else ""
            val bolusSuffix = if (bolusEvents.isNotEmpty()) ", with ${bolusEvents.size} bolus markers" else ""
            val a11yLabel = "Glucose trend chart showing ${readings.size} readings " +
                "over the last ${selectedPeriod.label}" + iobSuffix + basalSuffix + bolusSuffix

            val gestureModifier = if (isDetailMode) {
                Modifier
                    .pointerInput(selectedPeriod, nowMs) {
                        detectTransformGestures { _, pan, zoom, _ ->
                            // Dismiss tooltip on any gesture
                            tooltip = null

                            // Zoom: adjust visible span
                            val newSpan = (viewportSpan / zoom)
                                .toLong()
                                .coerceIn(MIN_VISIBLE_MS, fullPeriodMs)
                            viewportSpan = newSpan

                            // Pan: shift center by drag amount
                            if (size.width <= 0f) return@detectTransformGestures
                            val msPerPx = viewportSpan.toFloat() / size.width
                            val panMs = (pan.x * msPerPx).toLong()
                            val halfSpan = viewportSpan / 2
                            viewportCenter = (viewportCenter - panMs)
                                .coerceIn(fullStartMs + halfSpan, nowMs - halfSpan)
                        }
                    }
                    .pointerInput(readings, drawXMin, drawXMax) {
                        detectTapGestures(
                            onDoubleTap = {
                                // Reset zoom
                                viewportSpan = fullPeriodMs
                                viewportCenter = nowMs - fullPeriodMs / 2
                                tooltip = null
                            },
                            onTap = { offset ->
                                if (chartWidth <= 0f) return@detectTapGestures
                                // Convert tap x to timestamp
                                val tapFraction = ((offset.x - chartLeftPadding) / chartWidth)
                                    .coerceIn(0f, 1f)
                                val tapMs = drawXMin + (tapFraction * (drawXMax - drawXMin)).toLong()

                                // Find nearest reading via binary search (readings sorted by timestamp)
                                val proximityMs = ((drawXMax - drawXMin) * 0.03).toLong()
                                    .coerceIn(60_000L, 300_000L) // 1-5 min, scales with zoom
                                val nearest = findNearestReading(readings, tapMs)
                                if (nearest != null &&
                                    kotlin.math.abs(nearest.timestamp.toEpochMilli() - tapMs) < proximityMs
                                ) {
                                    val readingX = chartLeftPadding + chartWidth *
                                        (nearest.timestamp.toEpochMilli() - drawXMin).toFloat() /
                                        (drawXMax - drawXMin).toFloat()
                                    val clamped = nearest.glucoseMgDl.coerceIn(
                                        CHART_Y_MIN.toInt(),
                                        CHART_Y_MAX.toInt(),
                                    )
                                    val yRange = CHART_Y_MAX - CHART_Y_MIN
                                    val readingY = chartTopPadding + chartHeight *
                                        (1f - (clamped - CHART_Y_MIN) / yRange)
                                    tooltip = ChartTooltip(nearest, readingX, readingY)
                                } else {
                                    tooltip = null
                                }
                            },
                        )
                    }
            } else {
                Modifier
            }

            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .then(
                        if (isDetailMode) Modifier.weight(1f) else Modifier.height(280.dp),
                    ),
            ) {
                Canvas(
                    modifier = Modifier
                        .fillMaxSize()
                        .then(gestureModifier)
                        .testTag("glucose_chart")
                        .semantics { contentDescription = a11yLabel },
                ) {
                    // Capture layout params for hit-testing
                    val lp = 36.dp.toPx()
                    val rp = if (iobReadings.isNotEmpty()) 32.dp.toPx() else 8.dp.toPx()
                    val tp = 8.dp.toPx()
                    val bp = 24.dp.toPx()
                    chartLeftPadding = lp
                    chartWidth = size.width - lp - rp
                    chartTopPadding = tp
                    chartHeight = size.height - tp - bp

                    drawGlucoseChart(
                        readings = readings,
                        iobReadings = iobReadings,
                        basalReadings = basalReadings,
                        bolusEvents = bolusEvents,
                        xMin = drawXMin,
                        xMax = drawXMax,
                        textMeasurer = textMeasurer,
                        axisLabelColor = axisLabelColor,
                        gridColor = gridColor,
                        iobColor = iobColor,
                        thresholds = thresholds,
                    )
                }

                // Tooltip overlay (detail mode only)
                val tt = tooltip
                if (isDetailMode && tt != null) {
                    val timeStr = TOOLTIP_TIME_FORMAT.format(tt.reading.timestamp)
                    val color = glucoseColor(tt.reading.glucoseMgDl, thresholds)
                    // Use captured canvas dimensions for clamping
                    val ttWidthPx = 120.dp
                    val ttHeightPx = 56.dp
                    Box(
                        modifier = Modifier
                            .offset {
                                val totalW = chartLeftPadding + chartWidth
                                val totalH = chartTopPadding + chartHeight
                                val maxX = (totalW - ttWidthPx.toPx()).toInt().coerceAtLeast(0)
                                val maxY = (totalH - ttHeightPx.toPx()).toInt().coerceAtLeast(0)
                                IntOffset(
                                    (tt.canvasX - 60.dp.toPx()).toInt().coerceIn(0, maxX),
                                    (tt.canvasY - 56.dp.toPx()).toInt().coerceIn(0, maxY),
                                )
                            }
                            .background(
                                MaterialTheme.colorScheme.surfaceVariant,
                                RoundedCornerShape(8.dp),
                            )
                            .padding(horizontal = 10.dp, vertical = 6.dp),
                    ) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text(
                                text = "${tt.reading.glucoseMgDl} mg/dL",
                                style = MaterialTheme.typography.labelLarge,
                                color = color,
                            )
                            Text(
                                text = timeStr,
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
            }

            // Legend row
            Spacer(modifier = Modifier.height(if (isDetailMode) 4.dp else 6.dp))
            val basalModesPresent = remember(basalReadings) {
                buildSet {
                    for (r in basalReadings) {
                        when {
                            r.activityMode == PumpActivityMode.SLEEP -> add("sleep")
                            r.activityMode == PumpActivityMode.EXERCISE -> add("exercise")
                            r.isAutomated -> add("automated")
                            else -> add("manual")
                        }
                    }
                }
            }
            val bolusTypesPresent = remember(bolusEvents) {
                buildSet {
                    for (b in bolusEvents) {
                        when (DashboardComputations.deriveBolusType(b)) {
                            BolusType.AUTO_CORRECTION -> add("auto_correction")
                            BolusType.MEAL_WITH_CORRECTION -> add("meal_with_correction")
                            BolusType.CORRECTION -> add("manual_correction")
                            BolusType.AUTO -> add("auto_bolus")
                            BolusType.MEAL -> add("meal_bolus")
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
        if ("automated" in basalModesPresent) LegendItem(color = ChartColors.BasalAutomated, label = "Automated")
        if ("manual" in basalModesPresent) LegendItem(color = ChartColors.BasalManual, label = "Manual")
        if ("sleep" in basalModesPresent) LegendItem(color = ChartColors.BasalSleep, label = "Sleep")
        if ("exercise" in basalModesPresent) LegendItem(color = ChartColors.BasalExercise, label = "Exercise")
        if ("auto_correction" in bolusTypesPresent) LegendItem(color = ChartColors.Correction, label = "Auto Correction")
        if ("auto_bolus" in bolusTypesPresent) LegendItem(color = ChartColors.Correction, label = "Auto Bolus")
        if ("manual_correction" in bolusTypesPresent) LegendItem(color = ChartColors.ManualCorrection, label = "Manual Correction")
        if ("meal_with_correction" in bolusTypesPresent) LegendItem(color = ChartColors.MealWithCorrection, label = "Meal + Corr")
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

/** Binary search for the nearest reading to [targetMs] in a timestamp-sorted list. */
private fun findNearestReading(readings: List<CgmReading>, targetMs: Long): CgmReading? {
    if (readings.isEmpty()) return null
    var lo = 0
    var hi = readings.lastIndex
    while (lo < hi) {
        val mid = (lo + hi) / 2
        if (readings[mid].timestamp.toEpochMilli() < targetMs) lo = mid + 1 else hi = mid
    }
    // Check lo and lo-1 (the two candidates straddling targetMs)
    val candidates = listOfNotNull(
        readings.getOrNull(lo),
        readings.getOrNull(lo - 1),
    )
    return candidates.minByOrNull { kotlin.math.abs(it.timestamp.toEpochMilli() - targetMs) }
}

@Suppress("LongMethod")
private fun DrawScope.drawGlucoseChart(
    readings: List<CgmReading>,
    iobReadings: List<IoBReading>,
    basalReadings: List<BasalReading>,
    bolusEvents: List<BolusEvent>,
    xMin: Long,
    xMax: Long,
    textMeasurer: TextMeasurer,
    axisLabelColor: Color,
    gridColor: Color,
    iobColor: Color,
    thresholds: GlucoseThresholds = GlucoseThresholds(),
) {
    // Guard against zero-span viewport (prevents division by zero throughout)
    if (xMax <= xMin) return

    val leftPadding = 36.dp.toPx()
    val bottomPadding = 24.dp.toPx()
    val topPadding = 8.dp.toPx()
    val rightPadding = if (iobReadings.isNotEmpty()) 32.dp.toPx() else 8.dp.toPx()

    val chartWidth = size.width - leftPadding - rightPadding
    val chartHeight = size.height - topPadding - bottomPadding
    if (chartWidth <= 0f || chartHeight <= 0f) return

    val yMin = CHART_Y_MIN
    val yMax = CHART_Y_MAX
    val yRange = yMax - yMin

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

    // X-axis time labels (format adapts to visible duration)
    val visibleHours = (xMax - xMin) / 3_600_000L
    val timeFormatter = DateTimeFormatter.ofPattern(
        when {
            visibleHours <= 6 -> "h:mm"
            visibleHours <= 48 -> "ha"
            visibleHours <= 168 -> "EEE"
            else -> "M/d"
        },
    ).withZone(ZoneId.systemDefault())

    val tickCount = when {
        visibleHours <= 3 -> 3
        visibleHours <= 6 -> 3
        visibleHours <= 12 -> 4
        visibleHours <= 24 -> 4
        visibleHours <= 72 -> 3
        visibleHours <= 168 -> 7
        visibleHours <= 336 -> 7
        else -> 6
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
            reading.activityMode == PumpActivityMode.SLEEP -> ChartColors.BasalSleep
            reading.activityMode == PumpActivityMode.EXERCISE -> ChartColors.BasalExercise
            reading.isAutomated -> ChartColors.BasalAutomated
            else -> ChartColors.BasalManual
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
        val mode = reading.activityMode
        // Only draw overlays for sleep and exercise/activity modes
        if (mode != PumpActivityMode.SLEEP && mode != PumpActivityMode.EXERCISE) continue

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

        val color = if (mode == PumpActivityMode.SLEEP) {
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

        val bolusType = DashboardComputations.deriveBolusType(event)
        val color = when (bolusType) {
            BolusType.AUTO_CORRECTION -> ChartColors.Correction       // Pink: pump auto-correction
            BolusType.MEAL_WITH_CORRECTION -> ChartColors.MealWithCorrection // Purple: meal + correction combo
            BolusType.CORRECTION -> ChartColors.ManualCorrection      // Deep orange: user correction
            BolusType.AUTO -> ChartColors.Correction                  // Pink: other automated bolus
            BolusType.MEAL -> ChartColors.Bolus                       // Purple: meal bolus
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

        // Diamond marker -- color already set above from deriveBolusType()
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
