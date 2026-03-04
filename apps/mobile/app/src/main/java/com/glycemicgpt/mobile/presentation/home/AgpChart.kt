package com.glycemicgpt.mobile.presentation.home

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Fill
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.glycemicgpt.mobile.domain.model.AgpProfile

enum class AgpPeriod(val label: String, val days: Int) {
    SEVEN_DAYS("7D", 7),
    FOURTEEN_DAYS("14D", 14),
    THIRTY_DAYS("30D", 30),
}

private val AgpTeal = Color(0xFF14B8A6)
private const val AGP_Y_MIN = 20f
private const val AGP_Y_MAX = 300f

@Composable
fun AgpChart(
    profile: AgpProfile?,
    selectedPeriod: AgpPeriod,
    onPeriodSelected: (AgpPeriod) -> Unit,
    thresholds: GlucoseThresholds = GlucoseThresholds(),
    onClick: (() -> Unit)? = null,
    isDetailMode: Boolean = false,
    showPeriodSelector: Boolean = true,
    modifier: Modifier = Modifier,
) {
    val content: @Composable (Modifier) -> Unit = { innerModifier ->
        AgpChartContent(
            profile = profile,
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
private fun AgpChartContent(
    profile: AgpProfile?,
    selectedPeriod: AgpPeriod,
    onPeriodSelected: (AgpPeriod) -> Unit,
    thresholds: GlucoseThresholds,
    onClick: (() -> Unit)?,
    isDetailMode: Boolean,
    showPeriodSelector: Boolean,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier) {
        if (onClick != null) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "AGP Chart",
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                IconButton(
                    onClick = onClick,
                    modifier = Modifier
                        .size(48.dp)
                        .testTag("expand_agp_detail"),
                ) {
                    Icon(
                        imageVector = Icons.Default.OpenInFull,
                        contentDescription = "Expand AGP detail",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(20.dp),
                    )
                }
            }
            Spacer(modifier = Modifier.height(8.dp))
        }

        if (showPeriodSelector) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
            ) {
                AgpPeriod.entries.forEach { period ->
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
                            .testTag("agp_period_chip_${period.label}"),
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor = MaterialTheme.colorScheme.primary,
                            selectedLabelColor = MaterialTheme.colorScheme.onPrimary,
                        ),
                    )
                }
            }
            Spacer(modifier = Modifier.height(12.dp))
        }

        if (profile == null) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .then(
                        if (isDetailMode) Modifier.weight(1f) else Modifier.height(220.dp),
                    )
                    .testTag("agp_empty_state"),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = "Not enough data for AGP (minimum 3 days needed)",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                )
            }
        } else {
            val textMeasurer = rememberTextMeasurer()
            val axisLabelColor = MaterialTheme.colorScheme.onSurfaceVariant
            val gridColor = MaterialTheme.colorScheme.outline.copy(alpha = 0.3f)

            val a11yLabel = "Ambulatory glucose profile chart showing ${profile.totalReadings} " +
                "readings over ${profile.periodDays} days, " +
                "with median, interquartile, and 10th-90th percentile bands"

            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .then(
                        if (isDetailMode) Modifier.weight(1f) else Modifier.height(220.dp),
                    ),
            ) {
                Canvas(
                    modifier = Modifier
                        .fillMaxSize()
                        .testTag("agp_chart")
                        .semantics { contentDescription = a11yLabel },
                ) {
                    drawAgpChart(
                        profile = profile,
                        thresholds = thresholds,
                        textMeasurer = textMeasurer,
                        axisLabelColor = axisLabelColor,
                        gridColor = gridColor,
                    )
                }
            }
        }
    }
}

@Suppress("LongMethod")
private fun DrawScope.drawAgpChart(
    profile: AgpProfile,
    thresholds: GlucoseThresholds,
    textMeasurer: androidx.compose.ui.text.TextMeasurer,
    axisLabelColor: Color,
    gridColor: Color,
) {
    val leftPadding = 36.dp.toPx()
    val bottomPadding = 24.dp.toPx()
    val topPadding = 8.dp.toPx()
    val rightPadding = 8.dp.toPx()

    val chartWidth = size.width - leftPadding - rightPadding
    val chartHeight = size.height - topPadding - bottomPadding
    if (chartWidth <= 0f || chartHeight <= 0f) return

    val yMin = AGP_Y_MIN
    val yMax = AGP_Y_MAX
    val yRange = yMax - yMin

    fun yForGlucose(glucose: Float): Float =
        topPadding + chartHeight * (1f - (glucose.coerceIn(yMin, yMax) - yMin) / yRange)

    fun xForHour(hour: Int): Float =
        leftPadding + chartWidth * hour.toFloat() / 24f

    // Target range band
    val bandTopY = yForGlucose(thresholds.high.toFloat())
    val bandBottomY = yForGlucose(thresholds.low.toFloat())
    drawRect(
        color = Color(0xFF22C55E).copy(alpha = 0.08f),
        topLeft = Offset(leftPadding, bandTopY),
        size = androidx.compose.ui.geometry.Size(chartWidth, bandBottomY - bandTopY),
    )

    // Dashed threshold lines
    val dashedEffect = PathEffect.dashPathEffect(floatArrayOf(8f, 8f))
    listOf(thresholds.low.toFloat(), thresholds.high.toFloat()).forEach { value ->
        val y = yForGlucose(value)
        drawLine(
            color = gridColor,
            start = Offset(leftPadding, y),
            end = Offset(leftPadding + chartWidth, y),
            pathEffect = dashedEffect,
            strokeWidth = 1f,
        )
    }

    // Y-axis labels
    val labelStyle = TextStyle(fontSize = 10.sp, color = axisLabelColor)
    listOf(thresholds.low, thresholds.high).forEach { value ->
        val y = yForGlucose(value.toFloat())
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
    val xLabels = listOf(0 to "12 AM", 6 to "6 AM", 12 to "12 PM", 18 to "6 PM", 23 to "")
    xLabels.forEach { (hour, label) ->
        if (label.isEmpty()) return@forEach
        val x = xForHour(hour)
        val textResult = textMeasurer.measure(label, labelStyle)
        drawText(
            textResult,
            topLeft = Offset(
                x - textResult.size.width / 2f,
                size.height - bottomPadding + 4.dp.toPx(),
            ),
        )
    }

    val buckets = profile.buckets
    if (buckets.isEmpty()) return

    // Draw bands: p10-p25, p25-p75, p75-p90 (outer to inner)
    drawAgpBand(buckets, { it.p10 }, { it.p90 }, AgpTeal.copy(alpha = 0.15f), ::xForHour, ::yForGlucose)
    drawAgpBand(buckets, { it.p25 }, { it.p75 }, AgpTeal.copy(alpha = 0.30f), ::xForHour, ::yForGlucose)

    // Median line
    val medianPath = Path()
    var started = false
    for (bucket in buckets) {
        val x = xForHour(bucket.hour)
        val y = yForGlucose(bucket.p50)
        if (!started) {
            medianPath.moveTo(x, y)
            started = true
        } else {
            medianPath.lineTo(x, y)
        }
    }
    drawPath(
        medianPath,
        color = AgpTeal,
        style = androidx.compose.ui.graphics.drawscope.Stroke(width = 2.dp.toPx()),
    )
}

private fun DrawScope.drawAgpBand(
    buckets: List<com.glycemicgpt.mobile.domain.model.AgpBucket>,
    lower: (com.glycemicgpt.mobile.domain.model.AgpBucket) -> Float,
    upper: (com.glycemicgpt.mobile.domain.model.AgpBucket) -> Float,
    color: Color,
    xForHour: (Int) -> Float,
    yForGlucose: (Float) -> Float,
) {
    if (buckets.isEmpty()) return

    val path = Path()
    // Forward pass: upper boundary
    for (i in buckets.indices) {
        val x = xForHour(buckets[i].hour)
        val y = yForGlucose(upper(buckets[i]))
        if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
    }
    // Reverse pass: lower boundary
    for (i in buckets.indices.reversed()) {
        val x = xForHour(buckets[i].hour)
        val y = yForGlucose(lower(buckets[i]))
        path.lineTo(x, y)
    }
    path.close()

    drawPath(path, color, style = Fill)
}
