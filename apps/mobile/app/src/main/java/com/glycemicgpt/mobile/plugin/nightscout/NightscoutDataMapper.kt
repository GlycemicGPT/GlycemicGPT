package com.glycemicgpt.mobile.plugin.nightscout

import com.glycemicgpt.mobile.data.local.entity.BasalReadingEntity
import com.glycemicgpt.mobile.data.local.entity.BolusEventEntity
import com.glycemicgpt.mobile.data.local.entity.CgmReadingEntity
import com.glycemicgpt.mobile.data.remote.dto.NightscoutDataDto

/**
 * Maps the backend's Nightscout data slice (Story 43.8) into the Room entities
 * the BLE plugins also write, so the dashboard is source-agnostic. Pure and
 * synchronous so it's unit-testable without Android.
 *
 * Source attribution (AC4): every row carries `source = "nightscout-source"`
 * (cgm_readings, basal_readings, and bolus_events all have a `source` column).
 * Cross-source dedupe still works via the unique `timestampMs` (cgm/basal) and
 * `(units, timestampMs)` (bolus) indexes when a BLE plugin writes the same
 * reading.
 */
object NightscoutDataMapper {

    const val SOURCE = "nightscout-source"

    /** event_type values that map to a discrete insulin bolus. */
    private val BOLUS_TYPES = setOf("bolus", "correction", "combo_bolus")

    fun toCgmEntities(data: NightscoutDataDto): List<CgmReadingEntity> =
        data.glucoseReadings.map { r ->
            CgmReadingEntity(
                glucoseMgDl = r.value,
                trendArrow = r.trend,
                source = SOURCE,
                timestampMs = r.readingTimestamp.toEpochMilli(),
            )
        }

    fun toBolusEntities(data: NightscoutDataDto): List<BolusEventEntity> =
        data.pumpEvents
            .filter { it.eventType in BOLUS_TYPES && it.units != null }
            .map { e ->
                BolusEventEntity(
                    units = e.units!!,
                    isAutomated = e.isAutomated,
                    isCorrection = e.eventType == "correction",
                    source = SOURCE,
                    timestampMs = e.eventTimestamp.toEpochMilli(),
                )
            }

    fun toBasalEntities(data: NightscoutDataDto): List<BasalReadingEntity> =
        data.pumpEvents
            .filter { it.eventType == "basal" && it.units != null }
            .map { e ->
                BasalReadingEntity(
                    rate = e.units!!,
                    isAutomated = e.isAutomated,
                    activityMode = "",
                    source = SOURCE,
                    timestampMs = e.eventTimestamp.toEpochMilli(),
                )
            }
}
