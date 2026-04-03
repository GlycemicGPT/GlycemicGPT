package com.glycemicgpt.mobile.presentation.plugin

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.ui.semantics.Role
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Battery5Bar
import androidx.compose.material.icons.filled.Bluetooth
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.DeviceThermostat
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.LocalDrink
import androidx.compose.material.icons.filled.Medication
import androidx.compose.material.icons.filled.MonitorHeart
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.SignalCellularAlt
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.glycemicgpt.mobile.domain.plugin.ui.CardElement
import com.glycemicgpt.mobile.domain.plugin.ui.DashboardCardDescriptor
import com.glycemicgpt.mobile.domain.plugin.ui.LabelStyle
import com.glycemicgpt.mobile.domain.plugin.ui.PluginIcon
import com.glycemicgpt.mobile.domain.plugin.ui.UiColor

/**
 * Renders a [DashboardCardDescriptor] as a Material 3 card.
 */
internal const val MAX_NESTING_DEPTH = 5

@Composable
fun PluginDashboardCardRenderer(
    card: DashboardCardDescriptor,
    onClick: (() -> Unit)? = null,
) {
    val cardModifier = Modifier
        .fillMaxWidth()
        .testTag("plugin_card_${card.id}")
        .let { mod ->
            if (onClick != null) {
                mod.clickable(role = Role.Button, onClick = onClick)
            } else {
                mod
            }
        }
    Card(modifier = cardModifier) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = card.title,
                    style = MaterialTheme.typography.titleSmall,
                    modifier = Modifier.weight(1f),
                )
                if (onClick != null) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
                        contentDescription = "View details",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(20.dp),
                    )
                }
            }
            Spacer(modifier = Modifier.height(8.dp))
            card.elements.forEach { element ->
                RenderElement(element, depth = 0)
            }
        }
    }
}

@Composable
internal fun RenderElement(element: CardElement, depth: Int = 0) {
    if (depth > MAX_NESTING_DEPTH) return
    when (element) {
        is CardElement.LargeValue -> LargeValueElement(element)
        is CardElement.Label -> LabelElement(element)
        is CardElement.StatusBadge -> StatusBadgeElement(element)
        is CardElement.ProgressBar -> ProgressBarElement(element)
        is CardElement.IconValue -> IconValueElement(element)
        is CardElement.SparkLine -> SparkLineElement(element)
        is CardElement.Row -> RowElement(element, depth + 1)
        is CardElement.Column -> ColumnElement(element, depth + 1)
        is CardElement.Spacer -> Spacer(modifier = Modifier.height(element.heightDp.dp))
    }
}

@Composable
private fun LargeValueElement(element: CardElement.LargeValue) {
    Row(
        verticalAlignment = Alignment.Bottom,
    ) {
        Text(
            text = element.value,
            style = MaterialTheme.typography.headlineLarge,
            color = element.color.toComposeColor(),
        )
        if (element.unit.isNotEmpty()) {
            Spacer(modifier = Modifier.width(4.dp))
            Text(
                text = element.unit,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun LabelElement(element: CardElement.Label) {
    val style = when (element.style) {
        LabelStyle.TITLE -> MaterialTheme.typography.titleMedium
        LabelStyle.SUBTITLE -> MaterialTheme.typography.titleSmall
        LabelStyle.BODY -> MaterialTheme.typography.bodyMedium
        LabelStyle.CAPTION -> MaterialTheme.typography.bodySmall
    }
    Text(text = element.text, style = style)
}

@Composable
private fun StatusBadgeElement(element: CardElement.StatusBadge) {
    val resolvedColor = element.color.toComposeColor()
    val bgColor = resolvedColor.copy(alpha = 0.12f)
    val textColor = resolvedColor
    Surface(
        shape = RoundedCornerShape(4.dp),
        color = bgColor,
    ) {
        Text(
            text = element.text,
            style = MaterialTheme.typography.labelSmall,
            color = textColor,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
        )
    }
}

@Composable
private fun ProgressBarElement(element: CardElement.ProgressBar) {
    Column(modifier = Modifier.fillMaxWidth()) {
        if (element.label.isNotEmpty()) {
            Text(
                text = element.label,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(modifier = Modifier.height(4.dp))
        }
        LinearProgressIndicator(
            progress = { (element.value / element.max).coerceIn(0f, 1f) },
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun IconValueElement(element: CardElement.IconValue) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = element.icon.toImageVector(),
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(16.dp),
        )
        Spacer(modifier = Modifier.width(6.dp))
        Text(
            text = element.value,
            style = MaterialTheme.typography.bodyMedium,
        )
        if (element.label.isNotEmpty()) {
            Spacer(modifier = Modifier.width(4.dp))
            Text(
                text = element.label,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun SparkLineElement(element: CardElement.SparkLine) {
    Column(modifier = Modifier.fillMaxWidth()) {
        if (element.label.isNotEmpty()) {
            Text(
                text = element.label,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(modifier = Modifier.height(4.dp))
        }
        val lineColor = MaterialTheme.colorScheme.primary
        val strokeWidthPx = with(LocalDensity.current) { 2.dp.toPx() }
        Canvas(
            modifier = Modifier
                .fillMaxWidth()
                .height(40.dp),
        ) {
            if (element.values.size < 2) return@Canvas
            val minVal = element.values.min()
            val maxVal = element.values.max()
            val range = (maxVal - minVal).coerceAtLeast(1f)
            val stepX = size.width / (element.values.size - 1)
            for (i in 0 until element.values.size - 1) {
                val x1 = i * stepX
                val y1 = size.height - ((element.values[i] - minVal) / range) * size.height
                val x2 = (i + 1) * stepX
                val y2 = size.height - ((element.values[i + 1] - minVal) / range) * size.height
                drawLine(
                    color = lineColor,
                    start = Offset(x1, y1),
                    end = Offset(x2, y2),
                    strokeWidth = strokeWidthPx,
                )
            }
        }
    }
}

@Composable
private fun RowElement(element: CardElement.Row, depth: Int) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        element.elements.forEach { child ->
            RenderElement(child, depth)
        }
    }
}

@Composable
private fun ColumnElement(element: CardElement.Column, depth: Int) {
    Column(modifier = Modifier.fillMaxWidth()) {
        element.elements.forEach { child ->
            RenderElement(child, depth)
        }
    }
}

@Composable
private fun UiColor.toComposeColor(): Color = when (this) {
    UiColor.DEFAULT -> MaterialTheme.colorScheme.onSurface
    UiColor.SUCCESS -> Color(0xFF4CAF50)
    UiColor.WARNING -> Color(0xFFFF9800)
    UiColor.ERROR -> MaterialTheme.colorScheme.error
    UiColor.INFO -> MaterialTheme.colorScheme.primary
    UiColor.MUTED -> MaterialTheme.colorScheme.onSurfaceVariant
}

private fun PluginIcon.toImageVector(): ImageVector = when (this) {
    PluginIcon.BLUETOOTH -> Icons.Default.Bluetooth
    PluginIcon.BATTERY -> Icons.Default.Battery5Bar
    PluginIcon.RESERVOIR -> Icons.Default.LocalDrink
    PluginIcon.INSULIN -> Icons.Default.Medication
    PluginIcon.GLUCOSE -> Icons.Default.MonitorHeart
    PluginIcon.HEART_RATE -> Icons.Default.Favorite
    PluginIcon.SYNC -> Icons.Default.Sync
    PluginIcon.WARNING -> Icons.Default.Warning
    PluginIcon.CHECK -> Icons.Default.Check
    PluginIcon.CLOCK -> Icons.Default.Schedule
    PluginIcon.SETTINGS -> Icons.Default.Settings
    PluginIcon.SIGNAL -> Icons.Default.SignalCellularAlt
    PluginIcon.THERMOMETER -> Icons.Default.DeviceThermostat
}
