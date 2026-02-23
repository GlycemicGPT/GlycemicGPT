package com.glycemicgpt.mobile.ble.messages

import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.HistoryLogRecord
import com.glycemicgpt.mobile.domain.pump.HistoryLogParser
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Tandem-specific implementation of [HistoryLogParser].
 *
 * Delegates to [StatusResponseParser] static methods which contain the
 * actual byte-level parsing logic for Tandem pump history log events.
 */
@Singleton
class TandemHistoryLogParser @Inject constructor() : HistoryLogParser {

    override fun extractCgmFromHistoryLogs(records: List<HistoryLogRecord>, limits: SafetyLimits): List<CgmReading> =
        StatusResponseParser.extractCgmFromHistoryLogs(records, limits)

    override fun extractBolusesFromHistoryLogs(records: List<HistoryLogRecord>, limits: SafetyLimits): List<BolusEvent> =
        StatusResponseParser.extractBolusesFromHistoryLogs(records, limits)

    override fun extractBasalFromHistoryLogs(records: List<HistoryLogRecord>, limits: SafetyLimits): List<BasalReading> =
        StatusResponseParser.extractBasalFromHistoryLogs(records, limits)
}
