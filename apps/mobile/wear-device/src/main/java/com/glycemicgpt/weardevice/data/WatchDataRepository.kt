package com.glycemicgpt.weardevice.data

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

object WatchDataRepository {

    data class IoBState(
        val iob: Float,
        val timestampMs: Long,
    )

    data class CgmState(
        val mgDl: Int,
        val trend: String,
        val timestampMs: Long,
        val low: Int,
        val high: Int,
        val urgentLow: Int,
        val urgentHigh: Int,
    )

    data class AlertState(
        val type: String,
        val bgValue: Int,
        val timestampMs: Long,
        val message: String,
    )

    data class WatchFaceConfigState(
        val showIoB: Boolean = true,
        val showGraph: Boolean = true,
        val showAlert: Boolean = true,
        val showSeconds: Boolean = false,
        val graphRangeHours: Int = 3,
        val theme: String = "dark",
    )

    private val _iob = MutableStateFlow<IoBState?>(null)
    val iob: StateFlow<IoBState?> = _iob.asStateFlow()

    private val _cgm = MutableStateFlow<CgmState?>(null)
    val cgm: StateFlow<CgmState?> = _cgm.asStateFlow()

    private val _alert = MutableStateFlow<AlertState?>(null)
    val alert: StateFlow<AlertState?> = _alert.asStateFlow()

    private val _watchFaceConfig = MutableStateFlow(WatchFaceConfigState())
    val watchFaceConfig: StateFlow<WatchFaceConfigState> = _watchFaceConfig.asStateFlow()

    fun updateIoB(iob: Float, timestampMs: Long) {
        _iob.value = IoBState(iob, timestampMs)
    }

    fun updateCgm(
        mgDl: Int,
        trend: String,
        timestampMs: Long,
        low: Int,
        high: Int,
        urgentLow: Int,
        urgentHigh: Int,
    ) {
        _cgm.value = CgmState(mgDl, trend, timestampMs, low, high, urgentLow, urgentHigh)
    }

    fun updateAlert(type: String, bgValue: Int, timestampMs: Long, message: String) {
        _alert.value = if (type == "none") null else AlertState(type, bgValue, timestampMs, message)
    }

    private val VALID_GRAPH_RANGES = setOf(1, 3, 6)
    private val VALID_THEMES = setOf("dark", "clinical_blue", "high_contrast")

    fun updateWatchFaceConfig(
        showIoB: Boolean,
        showGraph: Boolean,
        showAlert: Boolean,
        showSeconds: Boolean,
        graphRangeHours: Int,
        theme: String,
    ) {
        _watchFaceConfig.value = WatchFaceConfigState(
            showIoB = showIoB,
            showGraph = showGraph,
            showAlert = showAlert,
            showSeconds = showSeconds,
            graphRangeHours = if (graphRangeHours in VALID_GRAPH_RANGES) graphRangeHours else 3,
            theme = if (theme in VALID_THEMES) theme else "dark",
        )
    }
}
