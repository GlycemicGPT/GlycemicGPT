/*
 * AC2: the history reader drives the IDD RACP over the C1 framework -- the plaintext count query, and
 * the multi-record report that collects SAKE-encrypted records on the IDD History Data characteristic
 * and terminates on the RACP success indication. Records are encrypted by a genuine two-sided SAKE
 * session and fragmented through PduFramer (MTU 23 discipline), in decrypt order.
 */
package com.glycemicgpt.mobile.ble.read

import com.glycemicgpt.mobile.ble.protocol.MedtronicProtocol
import com.glycemicgpt.mobile.ble.protocol.PduFramer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HistoryReaderTest {

    private val racp = MedtronicProtocol.RACP_UUID
    private val data = MedtronicProtocol.IDD_HISTORY_DATA_UUID
    private val features = MedtronicProtocol.IDD_FEATURES_UUID
    private val featuresPlain = hex("ffff006400fede801f") // E2E disabled

    // A small basal-rate-changed record (18 bytes): type 0x0099, seq 120, offset 0, new rate 0.5 IU/h.
    private val basalRecord = le16(0x0099) + le32(120) + le16(0) + hex("01" + "0a0000ff" + "050000ff" + "55")

    @Test
    fun `readRecordCount parses the RACP number-of-records response`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.onWrite = { characteristic, value ->
            if (characteristic == racp && value.contentEquals(HistoryReader.REQUEST_REPORT_NUMBER_OF_RECORDS)) {
                // 66 0f <count u16 LE> -> NUMBER_OF_RECORDS_RESPONSE / SEQUENCE_NUMBER / count=5.
                emit(racp, hex("660f0500"))
            }
        }

        var result: Result<Int>? = null
        HistoryReader(link, two.server).readRecordCount { result = it }
        assertEquals(5, result!!.getOrThrow())
    }

    @Test
    fun `readLastRecord collects one encrypted record and terminates on RACP success`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.reads[features] = two.pumpEncrypt(featuresPlain)
        link.onWrite = { characteristic, value ->
            if (characteristic == racp && value.contentEquals(HistoryReader.REQUEST_REPORT_LAST_RECORD)) {
                PduFramer.fragment(two.pumpEncrypt(basalRecord)).forEach { emit(data, it) }
                emit(racp, HistoryReader.EXPECTED_REPORT_SUCCESS)
            }
        }

        var result: Result<com.glycemicgpt.mobile.domain.model.HistoryLogRecord?>? = null
        HistoryReader(link, two.server).readLastRecord { result = it }

        val record = result!!.getOrThrow()
        assertNotNull(record)
        assertEquals(120, record!!.sequenceNumber)
        assertEquals(0x0099, record.eventTypeId)
    }

    @Test
    fun `readRecordsInRange collects multiple records, deduped`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.reads[features] = two.pumpEncrypt(featuresPlain)
        // Each record carries the optional context byte so it is 18 bytes (like basalRecord) and its
        // encrypted form has a short terminating PDU rather than landing on an exact PDU multiple.
        val rec1 = le16(0x0099) + le32(118) + le16(0) + hex("01" + "0a0000ff" + "050000ff" + "55")
        val rec2 = le16(0x0099) + le32(119) + le16(0) + hex("01" + "050000ff" + "0a0000ff" + "55")
        link.onWrite = { characteristic, value ->
            if (characteristic == racp && value.size > 3 &&
                value[0] == HistoryReader.REQUEST_REPORT_WITHIN_RANGE_PREFIX[0]
            ) {
                PduFramer.fragment(two.pumpEncrypt(rec1)).forEach { emit(data, it) }
                // Emit rec1 again (same sequence 118) so dedup is actually exercised end to end.
                PduFramer.fragment(two.pumpEncrypt(rec1)).forEach { emit(data, it) }
                PduFramer.fragment(two.pumpEncrypt(rec2)).forEach { emit(data, it) }
                emit(racp, HistoryReader.EXPECTED_REPORT_SUCCESS)
            }
        }

        var result: Result<List<com.glycemicgpt.mobile.domain.model.HistoryLogRecord>>? = null
        HistoryReader(link, two.server).readRecordsInRange(100, 120) { result = it }

        val records = result!!.getOrThrow()
        assertEquals(2, records.size)
        assertEquals(listOf(118, 119), records.map { it.sequenceNumber }.sorted())
    }

    @Test
    fun `readSinceSequence returns empty when already caught up`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.reads[features] = two.pumpEncrypt(featuresPlain)
        link.onWrite = { characteristic, value ->
            if (characteristic == racp && value.contentEquals(HistoryReader.REQUEST_REPORT_LAST_RECORD)) {
                PduFramer.fragment(two.pumpEncrypt(basalRecord)).forEach { emit(data, it) } // seq 120
                emit(racp, HistoryReader.EXPECTED_REPORT_SUCCESS)
            }
        }

        var result: Result<List<com.glycemicgpt.mobile.domain.model.HistoryLogRecord>>? = null
        HistoryReader(link, two.server).readSinceSequence(sinceSequence = 200) { result = it }

        assertTrue(result!!.getOrThrow().isEmpty())
    }

    @Test
    fun `readRecordCount fails on an unexpected RACP response`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.onWrite = { characteristic, _ ->
            if (characteristic == racp) emit(racp, hex("0f0f5a06")) // an error response code
        }

        var result: Result<Int>? = null
        HistoryReader(link, two.server).readRecordCount { result = it }
        assertTrue(result!!.isFailure)
    }

    private fun le16(v: Int): ByteArray = byteArrayOf((v and 0xFF).toByte(), ((v shr 8) and 0xFF).toByte())

    private fun le32(v: Int): ByteArray =
        byteArrayOf(
            (v and 0xFF).toByte(),
            ((v shr 8) and 0xFF).toByte(),
            ((v shr 16) and 0xFF).toByte(),
            ((v shr 24) and 0xFF).toByte(),
        )
}
