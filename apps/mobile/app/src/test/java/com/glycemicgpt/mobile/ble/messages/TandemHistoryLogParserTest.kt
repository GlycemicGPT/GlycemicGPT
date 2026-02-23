package com.glycemicgpt.mobile.ble.messages

import android.util.Base64
import com.glycemicgpt.mobile.domain.model.HistoryLogRecord
import com.glycemicgpt.mobile.domain.pump.HistoryLogParser
import io.mockk.every
import io.mockk.mockkStatic
import io.mockk.unmockkStatic
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Contract tests for [TandemHistoryLogParser] implementing [HistoryLogParser].
 *
 * Verifies that the parser correctly delegates to [StatusResponseParser] and
 * that the interface contract is satisfied.
 */
class TandemHistoryLogParserTest {

    private lateinit var parser: HistoryLogParser

    @Before
    fun setUp() {
        mockkStatic(Base64::class)
        every { Base64.encodeToString(any(), any()) } answers {
            java.util.Base64.getEncoder().encodeToString(firstArg<ByteArray>())
        }
        every { Base64.decode(any<String>(), any()) } answers {
            java.util.Base64.getDecoder().decode(firstArg<String>())
        }
        parser = TandemHistoryLogParser()
    }

    @After
    fun tearDown() {
        unmockkStatic(Base64::class)
    }

    /**
     * Build a 26-byte FFF8 stream record:
     *   eventTypeId(2) + pumpTimeSec(4) + seqNum(4) + data(16)
     */
    private fun buildStreamRecord(
        eventTypeId: Int,
        pumpTimeSec: Long,
        seq: Int,
        data: ByteArray,
    ): ByteArray {
        val buf = ByteBuffer.allocate(26).order(ByteOrder.LITTLE_ENDIAN)
        buf.putShort(eventTypeId.toShort())
        buf.putInt(pumpTimeSec.and(0xFFFFFFFFL).toInt())
        buf.putInt(seq)
        buf.put(data.copyOf(16))
        return buf.array()
    }

    private fun recordFromStream(
        eventTypeId: Int,
        pumpTimeSec: Long,
        seq: Int,
        data: ByteArray,
    ): HistoryLogRecord {
        val raw = buildStreamRecord(eventTypeId, pumpTimeSec, seq, data)
        return HistoryLogRecord(
            sequenceNumber = seq,
            rawBytesB64 = java.util.Base64.getEncoder().encodeToString(raw),
            eventTypeId = eventTypeId,
            pumpTimeSeconds = pumpTimeSec,
        )
    }

    @Test
    fun `extractCgmFromHistoryLogs returns empty for empty input`() {
        val result = parser.extractCgmFromHistoryLogs(emptyList())
        assertTrue(result.isEmpty())
    }

    @Test
    fun `extractBolusesFromHistoryLogs returns empty for empty input`() {
        val result = parser.extractBolusesFromHistoryLogs(emptyList())
        assertTrue(result.isEmpty())
    }

    @Test
    fun `extractBasalFromHistoryLogs returns empty for empty input`() {
        val result = parser.extractBasalFromHistoryLogs(emptyList())
        assertTrue(result.isEmpty())
    }

    @Test
    fun `extractCgmFromHistoryLogs parses G7 event type 399`() {
        // Event 399 = CGM G7 reading. Data format:
        // data[2] = 0x01 (valid), data[6:8] = glucose uint16 LE
        val data = ByteArray(16)
        data[2] = 0x01 // valid status
        val glucoseBytes = ByteBuffer.allocate(2).order(ByteOrder.LITTLE_ENDIAN).putShort(120).array()
        data[6] = glucoseBytes[0]
        data[7] = glucoseBytes[1]

        val pumpTime = 24 * 3600 * 365L // arbitrary time
        val record = recordFromStream(399, pumpTime, 1000, data)

        val result = parser.extractCgmFromHistoryLogs(listOf(record))
        assertEquals(1, result.size)
        assertEquals(120, result[0].glucoseMgDl)
    }

    @Test
    fun `extractBolusesFromHistoryLogs parses event type 280`() {
        // Event 280 = bolus delivery. Payload layout (16 bytes):
        //   0-1: bolusId, 2: deliveryStatus (0=Completed), 3: bolusTypeRaw,
        //   4: bolusSourceRaw, 5: remoteId, 6-7: requestedNow,
        //   8-9: correction, 10-11: requestedLater, 12-13: reserved,
        //   14-15: deliveredTotal (uint16 LE, milliunits)
        val data = ByteArray(16)
        val buf = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        buf.putShort(0, 1) // bolusId
        data[2] = 0x00 // deliveryStatus = Completed
        data[3] = 0x01 // bolusTypeRaw
        data[4] = 0x01 // bolusSourceRaw (user)
        buf.putShort(14, 2500) // deliveredTotal = 2500 milliunits = 2.5u

        val pumpTime = 572_000_000L // valid pump time
        val record = recordFromStream(280, pumpTime, 2000, data)

        val result = parser.extractBolusesFromHistoryLogs(listOf(record))
        assertEquals(1, result.size)
        assertEquals(2.5f, result[0].units, 0.01f)
    }

    @Test
    fun `extractBasalFromHistoryLogs parses event type 279`() {
        // Event 279 = basal delivery. Payload layout (16 bytes):
        //   0-1: commandedRateSourceRaw, 2-3: unknown,
        //   4-5: profileBasalRate (uint16 LE, milliunits/hr),
        //   6-7: commandedRate (uint16 LE, milliunits/hr, actual delivery)
        val data = ByteArray(16)
        val buf = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        buf.putShort(0, 1) // sourceRaw = 1 (user/profile)
        buf.putShort(4, 800) // profileRate = 800 milliunits/hr
        buf.putShort(6, 800) // commandedRate = 800 = 0.8u/hr

        val pumpTime = 572_000_000L // valid pump time
        val record = recordFromStream(279, pumpTime, 3000, data)

        val result = parser.extractBasalFromHistoryLogs(listOf(record))
        assertEquals(1, result.size)
        assertEquals(0.8f, result[0].rate, 0.01f)
        // sourceRaw=1 is not in AUTOMATED_BASAL_SOURCES (0,3,4)
        assertFalse(result[0].isAutomated)
    }

    @Test
    fun `extractBolusesFromHistoryLogs detects automated bolus`() {
        // bolusSourceRaw = 7 (Algorithm/Control-IQ) means automated
        val data = ByteArray(16)
        val buf = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        buf.putShort(0, 1) // bolusId
        data[2] = 0x00 // deliveryStatus = Completed
        data[3] = 0x08 // bolusTypeRaw = CORRECTION
        data[4] = 0x07 // bolusSourceRaw = Algorithm (automated)
        buf.putShort(14, 1500) // deliveredTotal = 1500 milliunits = 1.5u

        val pumpTime = 572_000_000L
        val record = recordFromStream(280, pumpTime, 6000, data)

        val result = parser.extractBolusesFromHistoryLogs(listOf(record))
        assertEquals(1, result.size)
        assertEquals(1.5f, result[0].units, 0.01f)
        assertTrue(result[0].isAutomated)
        assertTrue(result[0].isCorrection)
    }

    @Test
    fun `extractBolusesFromHistoryLogs rejects zero deliveredTotal`() {
        val data = ByteArray(16)
        val buf = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        buf.putShort(0, 1) // bolusId
        data[2] = 0x00 // deliveryStatus = Completed
        data[3] = 0x01 // bolusTypeRaw
        data[4] = 0x01 // bolusSourceRaw
        buf.putShort(14, 0) // deliveredTotal = 0 milliunits (should be rejected)

        val pumpTime = 572_000_000L
        val record = recordFromStream(280, pumpTime, 5000, data)

        val result = parser.extractBolusesFromHistoryLogs(listOf(record))
        assertTrue(result.isEmpty())
    }

    @Test
    fun `ignores unknown event types`() {
        val data = ByteArray(16)
        val pumpTime = 24 * 3600 * 365L
        val record = recordFromStream(999, pumpTime, 4000, data)

        assertTrue(parser.extractCgmFromHistoryLogs(listOf(record)).isEmpty())
        assertTrue(parser.extractBolusesFromHistoryLogs(listOf(record)).isEmpty())
        assertTrue(parser.extractBasalFromHistoryLogs(listOf(record)).isEmpty())
    }
}
