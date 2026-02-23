package com.glycemicgpt.mobile.domain.pump

import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.HistoryLogRecord

/**
 * Extracts typed pump events from raw history log records.
 *
 * History logs are pump-agnostic [HistoryLogRecord]s containing raw bytes.
 * Each pump implementation knows how to parse its own event format and
 * extract domain-level CGM readings, bolus events, and basal readings.
 *
 * All extraction methods accept [SafetyLimits] from the user's configured
 * settings. Implementations must use these limits to reject out-of-range
 * values rather than relying on hardcoded constants.
 */
interface HistoryLogParser {

    /**
     * Extract CGM readings from raw history log records.
     * Implementations must discard any reading outside the glucose range
     * defined by [limits].
     */
    fun extractCgmFromHistoryLogs(
        records: List<HistoryLogRecord>,
        limits: SafetyLimits = SafetyLimits(),
    ): List<CgmReading>

    /**
     * Extract bolus delivery events from raw history log records.
     * Implementations must discard any bolus exceeding the dose cap
     * defined by [limits].
     */
    fun extractBolusesFromHistoryLogs(
        records: List<HistoryLogRecord>,
        limits: SafetyLimits = SafetyLimits(),
    ): List<BolusEvent>

    /**
     * Extract basal delivery events from raw history log records.
     * Implementations must discard any basal rate exceeding the cap
     * defined by [limits].
     */
    fun extractBasalFromHistoryLogs(
        records: List<HistoryLogRecord>,
        limits: SafetyLimits = SafetyLimits(),
    ): List<BasalReading>
}
