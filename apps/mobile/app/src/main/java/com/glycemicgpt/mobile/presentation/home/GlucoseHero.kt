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
import com.glycemicgpt.mobile.domain.format.GlucoseFormat
import com.glycemicgpt.mobile.domain.freshness.Freshness
import com.glycemicgpt.mobile.domain.freshness.FreshnessPolicy
import com.glycemicgpt.mobile.domain.freshness.FreshnessThresholds
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BatteryStatus
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.model.GlucoseUnit
import com.glycemicgpt.mobile.domain.model.PumpActivityMode
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.model.ReservoirReading
import com.glycemicgpt.mobile.presentation.theme.GlucoseColors
import java.time.Instant

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
    glucoseUnit: GlucoseUnit = GlucoseUnit.MGDL,
    // Staleness policy for the primary glucose value. Overridable so the debug "fast staleness"
    // affordance (and tests) can drive the FRESH → STALE → TOO_STALE transitions deterministically.
    cgmThresholds: FreshnessThresholds = FreshnessPolicy.CGM,
    modifier: Modifier = Modifier,
) {
    // Always computed (a safe EPOCH stand-in when there's no reading) so the ticking effect keeps a
    // stable composition slot; only consumed when the corresponding value is present. Kept
    // unconditional (never called inside the per-metric `if` blocks below) so the composition
    // structure is stable regardless of which metrics are present.
    val cgmFreshness = rememberFreshness(cgm?.timestamp ?: Instant.EPOCH, cgmThresholds)
    val iobFreshness = rememberFreshness(iob?.timestamp ?: Instant.EPOCH, FreshnessPolicy.PUMP).freshness
    val basalFreshness = rememberFreshness(basalRate?.timestamp ?: Instant.EPOCH, FreshnessPolicy.PUMP).freshness
    val batteryFreshness = rememberFreshness(battery?.timestamp ?: Instant.EPOCH, FreshnessPolicy.PUMP).freshness
    val reservoirFreshness = rememberFreshness(reservoir?.timestamp ?: Instant.EPOCH, FreshnessPolicy.PUMP).freshness

    val a11yDescription = if (cgm != null) {
        buildString {
            append(
                "Glucose ${GlucoseFormat.format(cgm.glucoseMgDl, glucoseUnit)} " +
                    "${GlucoseFormat.spokenUnit(glucoseUnit)}, ",
            )
            append(cgm.trendArrow.name.lowercase().replace('_', ' '))
            // Safety: when the value is too old to be trusted as current, say so up front so a
            // TalkBack user is never read a stale number as if it were live.
            if (cgmFreshness.freshness == Freshness.TOO_STALE) {
                append(", reading is stale, last updated ${cgmFreshness.label}")
            }
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
                val tooStale = cgmFreshness.freshness == Freshness.TOO_STALE
                // Past TOO_STALE the value is no longer a confident live reading: drop the glucose
                // color and render it de-emphasised so it can't be mistaken for current.
                val color = if (tooStale) {
                    MaterialTheme.colorScheme.onSurfaceVariant
                } else {
                    glucoseColor(cgm.glucoseMgDl, thresholds)
                }

                // Primary: large glucose value + trend arrow
                Row(
                    verticalAlignment = Alignment.Bottom,
                    horizontalArrangement = Arrangement.Center,
                ) {
                    Text(
                        text = GlucoseFormat.format(cgm.glucoseMgDl, glucoseUnit),
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
                    text = GlucoseFormat.label(glucoseUnit),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )

                Spacer(modifier = Modifier.height(4.dp))
                // "Xm ago" caption + a Stale/Too-old badge that only appears once the reading is
                // past FRESH. On the golden path this is a fresh green caption with no badge.
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = cgmFreshness.label,
                        style = MaterialTheme.typography.labelSmall,
                        color = freshnessColor(cgmFreshness.freshness),
                    )
                    if (cgmFreshness.freshness != Freshness.FRESH) {
                        Spacer(modifier = Modifier.width(6.dp))
                        StalenessBadge(cgmFreshness.freshness)
                    }
                }

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
                                freshness = iobFreshness,
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
                                freshness = basalFreshness,
                                modifier = Modifier.testTag("hero_basal"),
                            )
                        }
                        if (battery != null) {
                            SecondaryMetric(
                                label = "Battery",
                                value = "${battery.percentage}%",
                                freshness = batteryFreshness,
                                modifier = Modifier.testTag("hero_battery"),
                            )
                        }
                        if (reservoir != null) {
                            SecondaryMetric(
                                label = "Reservoir",
                                value = "%.0fu".format(reservoir.unitsRemaining),
                                freshness = reservoirFreshness,
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
                    text = GlucoseFormat.label(glucoseUnit),
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
    freshness: Freshness = Freshness.FRESH,
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
            // A stale pump metric is de-emphasised so it doesn't read as a live value.
            color = if (freshness == Freshness.FRESH) {
                MaterialTheme.colorScheme.onSurface
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
        )
        if (freshness != Freshness.FRESH) {
            Spacer(modifier = Modifier.height(2.dp))
            StalenessBadge(freshness)
        }
    }
}
