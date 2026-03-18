package com.glycemicgpt.mobile.wear

import java.nio.ByteBuffer
import java.nio.ByteOrder

// MIRROR: Record format and sizes must stay in sync with
// wear-device/src/main/java/com/glycemicgpt/weardevice/data/WearHistorySerializer.kt
object WearHistorySerializer {

    // Basal record: rate(4) + timestamp(8) + flags(1) = 13 bytes
    const val BASAL_RECORD_SIZE = 13

    // Bolus record: units(4) + correctionUnits(4) + mealUnits(4) + timestamp(8) + flags(1) = 21 bytes
    const val BOLUS_RECORD_SIZE = 21

    // IoB record: iob(4) + timestamp(8) = 12 bytes
    const val IOB_RECORD_SIZE = 12

    // Flags encoding for basal: bit 0 = isAutomated, bits 1-2 = activityMode (0=NONE, 1=SLEEP, 2=EXERCISE)
    fun encodeBasalHistory(records: List<BasalRecord>): ByteArray {
        val buffer = ByteBuffer.allocate(records.size * BASAL_RECORD_SIZE)
            .order(ByteOrder.LITTLE_ENDIAN)
        for (r in records) {
            buffer.putFloat(r.rate)
            buffer.putLong(r.timestampMs)
            val flags = (if (r.isAutomated) 1 else 0) or (r.activityMode shl 1)
            buffer.put(flags.toByte())
        }
        return buffer.array()
    }

    fun encodeBolusHistory(records: List<BolusRecord>): ByteArray {
        val buffer = ByteBuffer.allocate(records.size * BOLUS_RECORD_SIZE)
            .order(ByteOrder.LITTLE_ENDIAN)
        for (r in records) {
            buffer.putFloat(r.units)
            buffer.putFloat(r.correctionUnits)
            buffer.putFloat(r.mealUnits)
            buffer.putLong(r.timestampMs)
            val flags = (if (r.isAutomated) 1 else 0) or (if (r.isCorrection) 2 else 0)
            buffer.put(flags.toByte())
        }
        return buffer.array()
    }

    fun encodeIoBHistory(records: List<IoBRecord>): ByteArray {
        val buffer = ByteBuffer.allocate(records.size * IOB_RECORD_SIZE)
            .order(ByteOrder.LITTLE_ENDIAN)
        for (r in records) {
            buffer.putFloat(r.iob)
            buffer.putLong(r.timestampMs)
        }
        return buffer.array()
    }

    data class BasalRecord(
        val rate: Float,
        val timestampMs: Long,
        val isAutomated: Boolean,
        val activityMode: Int, // 0=NONE, 1=SLEEP, 2=EXERCISE
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
