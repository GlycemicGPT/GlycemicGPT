package com.glycemicgpt.mobile.plugin.adapter

import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BolusEvent
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.HistoryLogRecord
import com.glycemicgpt.mobile.domain.plugin.asPumpStatus
import com.glycemicgpt.mobile.domain.pump.HistoryLogParser
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import com.glycemicgpt.mobile.plugin.PluginRegistry
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Bridges the deprecated [HistoryLogParser] interface to the plugin registry.
 */
@Suppress("DEPRECATION")
@Singleton
class HistoryLogParserAdapter @Inject constructor(
    private val registry: PluginRegistry,
) : HistoryLogParser {

    override fun extractCgmFromHistoryLogs(
        records: List<HistoryLogRecord>,
        limits: SafetyLimits,
    ): List<CgmReading> =
        registry.activePumpPlugin.value?.asPumpStatus()
            ?.extractCgmFromHistoryLogs(records, limits)
            ?: emptyList()

    override fun extractBolusesFromHistoryLogs(
        records: List<HistoryLogRecord>,
        limits: SafetyLimits,
    ): List<BolusEvent> =
        registry.activePumpPlugin.value?.asPumpStatus()
            ?.extractBolusesFromHistoryLogs(records, limits)
            ?: emptyList()

    override fun extractBasalFromHistoryLogs(
        records: List<HistoryLogRecord>,
        limits: SafetyLimits,
    ): List<BasalReading> =
        registry.activePumpPlugin.value?.asPumpStatus()
            ?.extractBasalFromHistoryLogs(records, limits)
            ?: emptyList()
}
