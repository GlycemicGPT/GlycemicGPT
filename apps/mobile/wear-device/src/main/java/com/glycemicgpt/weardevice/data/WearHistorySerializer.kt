package com.glycemicgpt.weardevice.data

import java.nio.ByteBuffer
import java.nio.ByteOrder

// MIRROR: Record format and sizes must stay in sync with
// app/src/main/java/com/glycemicgpt/mobile/wear/WearHistorySerializer.kt
object WearHistorySerializer {

    const val BASAL_RECORD_SIZE = 13
    const val BOLUS_RECORD_SIZE = 21
    const val IOB_RECORD_SIZE = 12

    /** Check that data has enough bytes, using Long arithmetic to prevent Int overflow. */
    private fun hasEnoughBytes(data: ByteArray, count: Int, recordSize: Int): Boolean {
        if (count < 0) return false
        val requiredBytes = count.toLong() * recordSize.toLong()
        return requiredBytes <= data.size.toLong()
    }

    fun decodeBasalHistory(data: ByteArray, count: Int): List<BasalRecord> {
        if (!hasEnoughBytes(data, count, BASAL_RECORD_SIZE)) return emptyList()
        val buffer = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        return (0 until count).map {
            val rate = buffer.float
            val timestampMs = buffer.long
            val flags = buffer.get().toInt() and 0xFF
            BasalRecord(
                rate = rate,
                timestampMs = timestampMs,
                isAutomated = (flags and 1) != 0,
                activityMode = (flags shr 1) and 0x03,
            )
        }
    }

    fun decodeBolusHistory(data: ByteArray, count: Int): List<BolusRecord> {
        if (!hasEnoughBytes(data, count, BOLUS_RECORD_SIZE)) return emptyList()
        val buffer = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        return (0 until count).map {
            val units = buffer.float
            val correctionUnits = buffer.float
            val mealUnits = buffer.float
            val timestampMs = buffer.long
            val flags = buffer.get().toInt() and 0xFF
            BolusRecord(
                units = units,
                correctionUnits = correctionUnits,
                mealUnits = mealUnits,
                timestampMs = timestampMs,
                isAutomated = (flags and 1) != 0,
                isCorrection = (flags and 2) != 0,
            )
        }
    }

    fun decodeIoBHistory(data: ByteArray, count: Int): List<IoBRecord> {
        if (!hasEnoughBytes(data, count, IOB_RECORD_SIZE)) return emptyList()
        val buffer = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        return (0 until count).map {
            IoBRecord(
                iob = buffer.float,
                timestampMs = buffer.long,
            )
        }
    }

    data class BasalRecord(
        val rate: Float,
        val timestampMs: Long,
        val isAutomated: Boolean,
        val activityMode: Int,
    )

    data class BolusRecord(
        val units: Float,
        val correctionUnits: Float,
        val mealUnits: Float,
        val timestampMs: Long,
        val isAutomated: Boolean,
        val isCorrection: Boolean,
    )

    data class IoBRecord(
        val iob: Float,
        val timestampMs: Long,
    )
}
