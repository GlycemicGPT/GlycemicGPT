package com.glycemicgpt.mobile.plugin.nightscout

import com.glycemicgpt.mobile.data.local.entity.BasalReadingEntity
import com.glycemicgpt.mobile.data.local.entity.BolusEventEntity
import com.glycemicgpt.mobile.data.local.entity.CgmReadingEntity
import com.glycemicgpt.mobile.data.remote.dto.NightscoutDataDto
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.pump.SafetyLimits

/**
 * Maps the backend's Nightscout data slice into the Room entities the BLE plugins
 * also write, so the dashboard is source-agnostic. Pure and synchronous so it's
 * unit-testable without Android.
 *
 * Source attribution: every row carries `source = "nightscout-source"` (cgm_readings,
 * basal_readings, and bolus_events all have a `source` column).
 *
 * Cross-source coexistence: a Nightscout row and a BLE row at the same timestamp
 * collapse to a single row via the unique `timestampMs` (cgm/basal) and
 * `(units, timestampMs)` (bolus) indexes -- they never both persist. The kept row
 * depends on the DAO's conflict strategy: cgm_readings/basal_readings batch inserts
 * use `IGNORE` (the existing row wins -- first writer), while bolus_events uses
 * `REPLACE` (the new row wins -- last writer). Either way there is no double-counting.
 *
 * Validation: out-of-range values from the backend are dropped at this ingestion
 * boundary (rather than throwing, which would abort a whole page) so the local DB
 * never stores physiologically impossible readings. The bounds mirror the platform's
 * own invariants ([CgmReading] requires 20..500 mg/dL; [BolusEvent] caps units at
 * [BolusEvent.MAX_BOLUS_UNITS]; basal rate is capped at the [SafetyLimits] absolute
 * ceiling); without this, such rows would be written and then silently discarded
 * again when the entity is mapped back to its domain model on read.
 */
object NightscoutDataMapper {

    const val SOURCE = "nightscout-source"

    /** Physiologically valid CGM range, matching [CgmReading]'s own invariant. */
    private val GLUCOSE_RANGE = CgmReading.MIN_MG_DL..CgmReading.MAX_MG_DL

    /** Hard upper bound for a basal rate (U/hr), reusing the platform safety ceiling. */
    private const val MAX_BASAL_RATE_U_HR = SafetyLimits.ABSOLUTE_MAX_BASAL_MILLIUNITS / 1000f

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
            // `in 0f..MAX` also rejects NaN/Infinity (out-of-range comparisons are false).
            .filter { it.eventType == "basal" && it.units != null && it.units in 0f..MAX_BASAL_RATE_U_HR }
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
