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

    private val _iob = MutableStateFlow<IoBState?>(null)
    val iob: StateFlow<IoBState?> = _iob.asStateFlow()

    private val _cgm = MutableStateFlow<CgmState?>(null)
    val cgm: StateFlow<CgmState?> = _cgm.asStateFlow()

    private val _alert = MutableStateFlow<AlertState?>(null)
    val alert: StateFlow<AlertState?> = _alert.asStateFlow()

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
}
