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
 */
interface HistoryLogParser {

    /**
     * Extract CGM readings from raw history log records.
     * Implementations must discard any reading outside the valid range (20-500 mg/dL).
     */
    fun extractCgmFromHistoryLogs(records: List<HistoryLogRecord>): List<CgmReading>

    /** Extract bolus delivery events from raw history log records. */
    fun extractBolusesFromHistoryLogs(records: List<HistoryLogRecord>): List<BolusEvent>

    /** Extract basal delivery events from raw history log records. */
    fun extractBasalFromHistoryLogs(records: List<HistoryLogRecord>): List<BasalReading>
}
