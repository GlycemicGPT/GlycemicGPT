package com.glycemicgpt.mobile.presentation.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BatteryStatus
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.model.PumpActivityMode
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.model.ReservoirReading
import com.glycemicgpt.mobile.presentation.theme.GlucoseColors

/**
 * Glucose threshold container. Defaults match the backend's default settings.
 * Use [GlucoseRangeStore] values at runtime for dynamic thresholds.
 */
data class GlucoseThresholds(
    val urgentLow: Int = DEFAULT_URGENT_LOW,
    val low: Int = DEFAULT_LOW,
    val high: Int = DEFAULT_HIGH,
    val urgentHigh: Int = DEFAULT_URGENT_HIGH,
) {
    companion object {
        const val DEFAULT_URGENT_LOW = 55
        const val DEFAULT_LOW = 70
        const val DEFAULT_HIGH = 180
        const val DEFAULT_URGENT_HIGH = 250
    }
}

fun glucoseColor(
    mgDl: Int,
    thresholds: GlucoseThresholds = GlucoseThresholds(),
): Color = when {
    mgDl <= thresholds.urgentLow -> GlucoseColors.UrgentLow
    mgDl <= thresholds.low -> GlucoseColors.Low
    mgDl < thresholds.high -> GlucoseColors.InRange
    mgDl < thresholds.urgentHigh -> GlucoseColors.High
    else -> GlucoseColors.UrgentHigh
}

fun trendArrowSymbol(trend: CgmTrend): String = when (trend) {
    CgmTrend.DOUBLE_UP -> "\u21C8"
    CgmTrend.SINGLE_UP -> "\u2191"
    CgmTrend.FORTY_FIVE_UP -> "\u2197"
    CgmTrend.FLAT -> "\u2192"
    CgmTrend.FORTY_FIVE_DOWN -> "\u2198"
    CgmTrend.SINGLE_DOWN -> "\u2193"
    CgmTrend.DOUBLE_DOWN -> "\u21CA"
    CgmTrend.UNKNOWN -> "?"
}

@Composable
fun GlucoseHero(
    cgm: CgmReading?,
    iob: IoBReading?,
    basalRate: BasalReading?,
    battery: BatteryStatus?,
    reservoir: ReservoirReading?,
    thresholds: GlucoseThresholds = GlucoseThresholds(),
    modifier: Modifier = Modifier,
) {
    val a11yDescription = if (cgm != null) {
        buildString {
            append("Glucose ${cgm.glucoseMgDl} milligrams per deciliter, ")
            append(cgm.trendArrow.name.lowercase().replace('_', ' '))
            if (iob != null) append(", insulin on board %.2f units".format(iob.iob))
            if (basalRate != null) append(", basal rate %.2f units per hour".format(basalRate.rate))
            if (battery != null) append(", battery ${battery.percentage} percent")
            if (reservoir != null) append(", reservoir %.0f units".format(reservoir.unitsRemaining))
        }
    } else {
        "No glucose data available"
    }

    Card(
        modifier = modifier
            .fillMaxWidth()
            .semantics { contentDescription = a11yDescription },
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface,
        ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            if (cgm != null) {
                val color = glucoseColor(cgm.glucoseMgDl, thresholds)

                // Primary: large glucose value + trend arrow
                Row(
                    verticalAlignment = Alignment.Bottom,
                    horizontalArrangement = Arrangement.Center,
                ) {
                    Text(
                        text = "${cgm.glucoseMgDl}",
                        fontSize = 64.sp,
                        fontWeight = FontWeight.Bold,
                        color = color,
                        modifier = Modifier.testTag("glucose_hero_value"),
                    )
                    Text(
                        text = trendArrowSymbol(cgm.trendArrow),
                        fontSize = 40.sp,
                        fontWeight = FontWeight.Bold,
                        color = color,
                        modifier = Modifier
                            .padding(bottom = 8.dp, start = 4.dp)
                            .testTag("glucose_hero_trend"),
                    )
                }

                Text(
                    text = "mg/dL",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )

                Spacer(modifier = Modifier.height(4.dp))
                FreshnessLabel(cgm.timestamp)

                // Secondary metrics: IoB + Basal + Battery + Reservoir
                if (iob != null || basalRate != null || battery != null || reservoir != null) {
                    Spacer(modifier = Modifier.height(12.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceEvenly,
                    ) {
                        if (iob != null) {
                            SecondaryMetric(
                                label = "IoB",
                                value = "%.2fu".format(iob.iob),
                                modifier = Modifier.testTag("hero_iob"),
                            )
                        }
                        if (basalRate != null) {
                            val basalText = "%.2f u/hr".format(basalRate.rate)
                            val modeLabel = when (basalRate.activityMode) {
                                PumpActivityMode.SLEEP -> " Sleep"
                                PumpActivityMode.EXERCISE -> " Exercise"
                                PumpActivityMode.NONE -> if (basalRate.isAutomated) " Automated" else ""
                            }
                            SecondaryMetric(
                                label = "Basal",
                                value = basalText + modeLabel,
                                modifier = Modifier.testTag("hero_basal"),
                            )
                        }
                        if (battery != null) {
                            SecondaryMetric(
                                label = "Battery",
                                value = "${battery.percentage}%",
                                modifier = Modifier.testTag("hero_battery"),
                            )
                        }
                        if (reservoir != null) {
                            SecondaryMetric(
                                label = "Reservoir",
                                value = "%.0fu".format(reservoir.unitsRemaining),
                                modifier = Modifier.testTag("hero_reservoir"),
                            )
                        }
                    }
                }
            } else {
                Text(
                    text = "--",
                    fontSize = 64.sp,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = "mg/dL",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun SecondaryMetric(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = modifier,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
}
