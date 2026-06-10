package com.glycemicgpt.mobile.plugin.nightscout

import com.glycemicgpt.mobile.data.local.entity.BasalReadingEntity
import com.glycemicgpt.mobile.data.local.entity.BolusEventEntity
import com.glycemicgpt.mobile.data.local.entity.CgmReadingEntity
import com.glycemicgpt.mobile.data.remote.dto.NightscoutDataDto
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.CgmReading

/**
 * Maps the backend's Nightscout data slice (Story 43.8) into the Room entities
 * the BLE plugins also write, so the dashboard is source-agnostic. Pure and
 * synchronous so it's unit-testable without Android.
 *
 * Source attribution (AC4): every row carries `source = "nightscout-source"`
 * (cgm_readings, basal_readings, and bolus_events all have a `source` column).
 * Cross-source coexistence (AC5) is last-writer-wins by timestamp: the unique
 * `timestampMs` (cgm/basal) and `(units, timestampMs)` (bolus) indexes mean a
 * Nightscout row and a BLE row at the same timestamp collapse to one row (the
 * later write wins and its `source` is what's kept) -- they do not both persist.
 *
 * Validation: out-of-range values from the backend are dropped at this ingestion
 * boundary (rather than throwing, which would abort a whole page) so the local DB
 * never stores physiologically impossible readings. The bounds mirror the domain
 * models' own invariants ([CgmReading] requires 20..500 mg/dL; [BolusEvent] caps
 * units at [BolusEvent.MAX_BOLUS_UNITS]); without this, such rows would be written
 * and then silently discarded again when the entity is mapped back to its domain
 * model on read.
 */
object NightscoutDataMapper {

    const val SOURCE = "nightscout-source"

    /** Physiologically valid CGM range, matching [CgmReading]'s own invariant. */
    private val GLUCOSE_RANGE = CgmReading.MIN_MG_DL..CgmReading.MAX_MG_DL

    /**
     * event_type values that map to a discrete insulin bolus. `combo_bolus` is
     * deliberately excluded: the backend taxonomy uses it for either a real combo
     * bolus or an AAPS extendedEmulated temp-basal-rate, whose `units` is the
     * extended portion rather than a point-in-time dose -- counting it here would
     * inflate bolus totals / IoB. It is left out until its semantics are validated.
     */
    private val BOLUS_TYPES = setOf("bolus", "correction")

    fun toCgmEntities(data: NightscoutDataDto): List<CgmReadingEntity> =
        data.glucoseReadings
            .filter { it.value in GLUCOSE_RANGE }
            .map { r ->
                CgmReadingEntity(
                    glucoseMgDl = r.value,
                    trendArrow = r.trend,
                    source = SOURCE,
                    timestampMs = r.readingTimestamp.toEpochMilli(),
                )
            }

    fun toBolusEntities(data: NightscoutDataDto): List<BolusEventEntity> =
        data.pumpEvents
            .filter { it.eventType in BOLUS_TYPES && it.units != null && it.units in BOLUS_RANGE }
            .map { e ->
                val isCorrection = e.eventType == "correction"
                BolusEventEntity(
                    units = e.units!!,
                    // A `correction` is by definition an automated (Control-IQ-style) correction in
                    // the platform taxonomy, so it is automated regardless of the upload's flag;
                    // user-initiated doses arrive as `bolus`.
                    isAutomated = e.isAutomated || isCorrection,
                    isCorrection = isCorrection,
                    source = SOURCE,
                    timestampMs = e.eventTimestamp.toEpochMilli(),
                )
            }

    fun toBasalEntities(data: NightscoutDataDto): List<BasalReadingEntity> =
        data.pumpEvents
            .filter { it.eventType == "basal" && it.units != null && it.units >= 0f && it.units.isFinite() }
            .map { e ->
                BasalReadingEntity(
                    rate = e.units!!,
                    isAutomated = e.isAutomated,
                    // Nightscout basal events carry no pump activity mode (sleep/exercise); leave it
                    // blank, matching how BLE writers leave fields they don't observe.
                    activityMode = "",
                    source = SOURCE,
                    timestampMs = e.eventTimestamp.toEpochMilli(),
                )
            }

    /** Discrete-bolus dose bounds, mirroring [BolusEvent]'s hard cap. */
    private val BOLUS_RANGE = 0f..BolusEvent.MAX_BOLUS_UNITS
}
