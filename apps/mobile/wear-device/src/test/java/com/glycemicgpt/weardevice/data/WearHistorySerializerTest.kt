package com.glycemicgpt.weardevice.data

import org.junit.Assert.assertEquals
import org.junit.Test

class WearHistorySerializerTest {

    @Test
    fun `basal round-trip preserves all fields`() {
        val records = listOf(
            WearHistorySerializer.BasalRecord(0.8f, 1_700_000_000_000L, true, 0),
            WearHistorySerializer.BasalRecord(1.2f, 1_700_000_300_000L, false, 1),
            WearHistorySerializer.BasalRecord(0.5f, 1_700_000_600_000L, true, 2),
        )
        // Encode using the same format the app module uses
        val data = encodeBasalHistory(records)
        val decoded = WearHistorySerializer.decodeBasalHistory(data, records.size)

        assertEquals(records.size, decoded.size)
        records.zip(decoded).forEach { (expected, actual) ->
            assertEquals(expected.rate, actual.rate, 0.001f)
            assertEquals(expected.timestampMs, actual.timestampMs)
            assertEquals(expected.isAutomated, actual.isAutomated)
            assertEquals(expected.activityMode, actual.activityMode)
        }
    }

    @Test
    fun `bolus round-trip preserves all fields`() {
        val records = listOf(
            WearHistorySerializer.BolusRecord(2.5f, 0.3f, 2.2f, 1_700_000_000_000L, false, false),
            WearHistorySerializer.BolusRecord(0.1f, 0.1f, 0f, 1_700_000_300_000L, true, true),
        )
        val data = encodeBolusHistory(records)
        val decoded = WearHistorySerializer.decodeBolusHistory(data, records.size)

        assertEquals(records.size, decoded.size)
        records.zip(decoded).forEach { (expected, actual) ->
            assertEquals(expected.units, actual.units, 0.001f)
            assertEquals(expected.correctionUnits, actual.correctionUnits, 0.001f)
            assertEquals(expected.mealUnits, actual.mealUnits, 0.001f)
            assertEquals(expected.timestampMs, actual.timestampMs)
            assertEquals(expected.isAutomated, actual.isAutomated)
            assertEquals(expected.isCorrection, actual.isCorrection)
        }
    }

    @Test
    fun `iob round-trip preserves all fields`() {
        val records = listOf(
            WearHistorySerializer.IoBRecord(3.2f, 1_700_000_000_000L),
            WearHistorySerializer.IoBRecord(0.5f, 1_700_000_300_000L),
        )
        val data = encodeIoBHistory(records)
        val decoded = WearHistorySerializer.decodeIoBHistory(data, records.size)

        assertEquals(records.size, decoded.size)
        records.zip(decoded).forEach { (expected, actual) ->
            assertEquals(expected.iob, actual.iob, 0.001f)
            assertEquals(expected.timestampMs, actual.timestampMs)
        }
    }

    @Test
    fun `decode returns empty list for undersized data`() {
        assertEquals(emptyList<Any>(), WearHistorySerializer.decodeBasalHistory(byteArrayOf(0), 1))
        assertEquals(emptyList<Any>(), WearHistorySerializer.decodeBolusHistory(byteArrayOf(0), 1))
        assertEquals(emptyList<Any>(), WearHistorySerializer.decodeIoBHistory(byteArrayOf(0), 1))
    }

    // Encode helpers that mirror the app module's WearHistorySerializer.encode* methods
    // (watch module only has decoders, so we inline the encode logic for testing)
    private fun encodeBasalHistory(records: List<WearHistorySerializer.BasalRecord>): ByteArray {
        val buffer = java.nio.ByteBuffer.allocate(records.size * WearHistorySerializer.BASAL_RECORD_SIZE)
            .order(java.nio.ByteOrder.LITTLE_ENDIAN)
        for (r in records) {
            buffer.putFloat(r.rate)
            buffer.putLong(r.timestampMs)
            val flags = (if (r.isAutomated) 1 else 0) or (r.activityMode shl 1)
            buffer.put(flags.toByte())
        }
        return buffer.array()
    }

    private fun encodeBolusHistory(records: List<WearHistorySerializer.BolusRecord>): ByteArray {
        val buffer = java.nio.ByteBuffer.allocate(records.size * WearHistorySerializer.BOLUS_RECORD_SIZE)
            .order(java.nio.ByteOrder.LITTLE_ENDIAN)
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

    private fun encodeIoBHistory(records: List<WearHistorySerializer.IoBRecord>): ByteArray {
        val buffer = java.nio.ByteBuffer.allocate(records.size * WearHistorySerializer.IOB_RECORD_SIZE)
            .order(java.nio.ByteOrder.LITTLE_ENDIAN)
        for (r in records) {
            buffer.putFloat(r.iob)
            buffer.putLong(r.timestampMs)
        }
        return buffer.array()
    }
}
