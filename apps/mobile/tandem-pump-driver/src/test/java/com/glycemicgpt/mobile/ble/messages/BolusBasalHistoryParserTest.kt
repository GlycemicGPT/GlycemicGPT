package com.glycemicgpt.mobile.ble.messages

import android.util.Base64
import com.glycemicgpt.mobile.domain.model.ControlIqMode
import com.glycemicgpt.mobile.domain.model.HistoryLogRecord
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import io.mockk.every
import io.mockk.mockkStatic
import io.mockk.unmockkStatic
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder

class BolusBasalHistoryParserTest {

    @Before
    fun setUp() {
        mockkStatic(Base64::class)
        every { Base64.encodeToString(any(), any()) } answers {
            java.util.Base64.getEncoder().encodeToString(firstArg<ByteArray>())
        }
        every { Base64.decode(any<String>(), any()) } answers {
            java.util.Base64.getDecoder().decode(firstArg<String>())
        }
    }

    @After
    fun tearDown() {
        unmockkStatic(Base64::class)
    }

    // Valid pump time for Feb 2026 (~572 million seconds since Tandem epoch)
    private val validPumpTime = 572_000_000L

    /**
     * Build a 26-byte FFF8 stream record:
     *   eventTypeId(2) + pumpTimeSec(4) + recordIndex(4) + data(16)
     */
    private fun buildStreamRecord(
        seq: Int,
        pumpTimeSec: Long,
        eventTypeId: Int,
        data: ByteArray = ByteArray(16),
    ): ByteArray {
        val buf = ByteBuffer.allocate(26).order(ByteOrder.LITTLE_ENDIAN)
        buf.putShort(eventTypeId.toShort())
        buf.putInt(pumpTimeSec.toInt())
        buf.putInt(seq)
        buf.put(data.copyOf(16))
        return buf.array()
    }

    /**
     * Build a 16-byte bolus delivery payload (event 280) using raw BLE layout.
     *
     *   bytes 0-1: bolusId (uint16 LE)
     *   byte  2: bolusDeliveryStatusRaw (0=Completed, 1=Started)
     *   byte  3: bolusTypeRaw (0x08 bit = correction)
     *   byte  4: bolusSourceRaw (7=Algorithm/Control-IQ)
     *   byte  5: remoteId
     *   bytes 6-7: requestedNow (uint16 LE, milliunits)
     *   bytes 8-9: correction (uint16 LE, milliunits)
     *   bytes 10-11: requestedLater (uint16 LE, milliunits)
     *   bytes 12-13: reserved
     *   bytes 14-15: deliveredTotal (uint16 LE, milliunits)
     */
    private fun buildBolusData(
        bolusTypeRaw: Int = 0x01,
        deliveryStatus: Int = 0,
        bolusId: Int = 1,
        requestedNow: Int = 0,
        remoteId: Int = 0,
        bolusSourceRaw: Int = 1,
        correction: Int = 0,
        requestedLater: Int = 0,
        deliveredTotal: Int = 2500,
    ): ByteArray {
        val data = ByteArray(16)
        val buf = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        buf.putShort(0, bolusId.toShort())
        data[2] = deliveryStatus.toByte()
        data[3] = bolusTypeRaw.toByte()
        data[4] = bolusSourceRaw.toByte()
        data[5] = remoteId.toByte()
        buf.putShort(6, requestedNow.toShort())
        buf.putShort(8, correction.toShort())
        buf.putShort(10, requestedLater.toShort())
        buf.putShort(14, deliveredTotal.toShort())
        return data
    }

    /**
     * Build a 16-byte basal delivery payload (event 279).
     *
     *   bytes 0-1: commandedRateSourceRaw (uint16 LE)
     *   bytes 2-3: unknown
     *   bytes 4-5: profileBasalRate (uint16 LE, milliunits/hr)
     *   bytes 6-7: commandedRate (uint16 LE, milliunits/hr) -- actual delivery
     *   bytes 8-9: algorithmRate/tempRate
     *   bytes 10-15: padding
     */
    private fun buildBasalData(
        sourceRaw: Int = 1,
        profileRate: Int = 800,
        commandedRate: Int = 800,
    ): ByteArray {
        val data = ByteArray(16)
        val buf = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        buf.putShort(0, sourceRaw.toShort())
        buf.putShort(4, profileRate.toShort())
        buf.putShort(6, commandedRate.toShort())
        return data
    }

    private fun makeRecord(
        seq: Int,
        eventTypeId: Int,
        pumpTimeSec: Long,
        data: ByteArray,
    ): HistoryLogRecord {
        val rawBytes = buildStreamRecord(seq, pumpTimeSec, eventTypeId, data)
        return HistoryLogRecord(
            sequenceNumber = seq,
            eventTypeId = eventTypeId,
            pumpTimeSeconds = pumpTimeSec,
            rawBytesB64 = java.util.Base64.getEncoder().encodeToString(rawBytes),
        )
    }

    // =======================================================================
    // Bolus Delivery Payload Tests
    // =======================================================================

    @Test
    fun `parseBolusDeliveryPayload with valid completed bolus`() {
        val data = buildBolusData(deliveredTotal = 2500, deliveryStatus = 0)
        val result = StatusResponseParser.parseBolusDeliveryPayload(data, validPumpTime)
        assertNotNull(result)
        assertEquals(2.5f, result!!.units, 0.001f)
    }

    @Test
    fun `parseBolusDeliveryPayload skips started status`() {
        val data = buildBolusData(deliveredTotal = 2500, deliveryStatus = 1)
        val result = StatusResponseParser.parseBolusDeliveryPayload(data, validPumpTime)
        assertNull(result)
    }

    @Test
    fun `parseBolusDeliveryPayload with zero deliveredTotal returns null`() {
        val data = buildBolusData(deliveredTotal = 0)
        val result = StatusResponseParser.parseBolusDeliveryPayload(data, validPumpTime)
        assertNull(result)
    }

    @Test
    fun `parseBolusDeliveryPayload with large deliveredTotal rejected by default cap`() {
        // 60000mu = 60u exceeds default cap of 25000mu (25u)
        val data = buildBolusData(deliveredTotal = 60000)
        val result = StatusResponseParser.parseBolusDeliveryPayload(data, validPumpTime)
        assertNull(result)
    }

    @Test
    fun `parseBolusDeliveryPayload accepts bolus at absolute ceiling`() {
        // Absolute max bolus is 25000mu (25u) matching Tandem hardware
        val maxAllowed = SafetyLimits(maxBolusDoseMilliunits = SafetyLimits.ABSOLUTE_MAX_BOLUS_MILLIUNITS)
        val data = buildBolusData(deliveredTotal = 25000)
        val result = StatusResponseParser.parseBolusDeliveryPayload(data, validPumpTime, maxAllowed)
        assertNotNull(result)
        assertEquals(25.0f, result!!.units, 0.001f)
    }

    @Test
    fun `parseBolusDeliveryPayload detects algorithm automation`() {
        val data = buildBolusData(bolusSourceRaw = 7, bolusTypeRaw = 0x01)
        val result = StatusResponseParser.parseBolusDeliveryPayload(data, validPumpTime)
        assertNotNull(result)
        assertTrue(result!!.isAutomated)
        assertFalse(result.isCorrection)
    }

    @Test
    fun `parseBolusDeliveryPayload detects user-initiated correction`() {
        // User-initiated correction (source=1, not Algorithm) is NOT automated
        val data = buildBolusData(bolusTypeRaw = 0x09, bolusSourceRaw = 1)
        val result = StatusResponseParser.parseBolusDeliveryPayload(data, validPumpTime)
        assertNotNull(result)
        assertTrue(result!!.isCorrection)
        assertFalse(result.isAutomated) // user-initiated, not algorithm
    }

    @Test
    fun `parseBolusDeliveryPayload detects algorithm-initiated correction`() {
        // Algorithm correction (source=7) IS automated
        val data = buildBolusData(bolusTypeRaw = 0x09, bolusSourceRaw = 7)
        val result = StatusResponseParser.parseBolusDeliveryPayload(data, validPumpTime)
        assertNotNull(result)
        assertTrue(result!!.isCorrection)
        assertTrue(result.isAutomated)
    }

    @Test
    fun `parseBolusDeliveryPayload manual non-correction bolus`() {
        val data = buildBolusData(bolusTypeRaw = 0x01, bolusSourceRaw = 1)
        val result = StatusResponseParser.parseBolusDeliveryPayload(data, validPumpTime)
        assertNotNull(result)
        assertFalse(result!!.isAutomated)
        assertFalse(result.isCorrection)
    }

    @Test
    fun `parseBolusDeliveryPayload with short payload returns null`() {
        val data = ByteArray(14) // too short (need 16)
        val result = StatusResponseParser.parseBolusDeliveryPayload(data, validPumpTime)
        assertNull(result)
    }

    @Test
    fun `parseBolusDeliveryPayload small bolus 100 milliunits`() {
        val data = buildBolusData(deliveredTotal = 100)
        val result = StatusResponseParser.parseBolusDeliveryPayload(data, validPumpTime)
        assertNotNull(result)
        assertEquals(0.1f, result!!.units, 0.001f)
    }

    // =======================================================================
    // Bolus Extraction Tests
    // =======================================================================

    @Test
    fun `extractBolusesFromHistoryLogs filters only event 280`() {
        val bolusData = buildBolusData(deliveredTotal = 3000)
        val cgmData = ByteArray(16)
        val records = listOf(
            makeRecord(1, 280, validPumpTime, bolusData),
            makeRecord(2, 399, validPumpTime + 300, cgmData),
            makeRecord(3, 279, validPumpTime + 600, ByteArray(16)),
        )
        val result = StatusResponseParser.extractBolusesFromHistoryLogs(records)
        assertEquals(1, result.size)
        assertEquals(3.0f, result[0].units, 0.001f)
    }

    @Test
    fun `extractBolusesFromHistoryLogs skips started boluses`() {
        val completed = buildBolusData(deliveredTotal = 2000, deliveryStatus = 0)
        val started = buildBolusData(deliveredTotal = 2000, deliveryStatus = 1)
        val records = listOf(
            makeRecord(1, 280, validPumpTime, completed),
            makeRecord(2, 280, validPumpTime + 60, started),
        )
        val result = StatusResponseParser.extractBolusesFromHistoryLogs(records)
        assertEquals(1, result.size)
    }

    @Test
    fun `extractBolusesFromHistoryLogs returns sorted by timestamp`() {
        val bolus1 = buildBolusData(deliveredTotal = 1000)
        val bolus2 = buildBolusData(deliveredTotal = 2000)
        val records = listOf(
            makeRecord(2, 280, validPumpTime + 300, bolus2),
            makeRecord(1, 280, validPumpTime, bolus1),
        )
        val result = StatusResponseParser.extractBolusesFromHistoryLogs(records)
        assertEquals(2, result.size)
        assertEquals(1.0f, result[0].units, 0.001f) // earlier timestamp first
        assertEquals(2.0f, result[1].units, 0.001f)
    }

    // =======================================================================
    // Basal Delivery Payload Tests
    // =======================================================================

    @Test
    fun `parseBasalDeliveryPayload with valid profile rate`() {
        val data = buildBasalData(sourceRaw = 1, commandedRate = 800)
        val result = StatusResponseParser.parseBasalDeliveryPayload(data, validPumpTime)
        assertNotNull(result)
        assertEquals(0.8f, result!!.rate, 0.001f)
        assertFalse(result.isAutomated)
        assertEquals(ControlIqMode.STANDARD, result.controlIqMode)
    }

    @Test
    fun `parseBasalDeliveryPayload with suspended source`() {
        val data = buildBasalData(sourceRaw = 0, commandedRate = 0)
        val result = StatusResponseParser.parseBasalDeliveryPayload(data, validPumpTime)
        assertNotNull(result)
        assertEquals(0f, result!!.rate, 0.001f)
        assertTrue(result.isAutomated) // suspended is automated
    }

    @Test
    fun `parseBasalDeliveryPayload detects algorithm source`() {
        val data = buildBasalData(sourceRaw = 3, commandedRate = 1200)
        val result = StatusResponseParser.parseBasalDeliveryPayload(data, validPumpTime)
        assertNotNull(result)
        assertEquals(1.2f, result!!.rate, 0.001f)
        assertTrue(result.isAutomated)
    }

    @Test
    fun `parseBasalDeliveryPayload detects temp plus algorithm`() {
        val data = buildBasalData(sourceRaw = 4, commandedRate = 500)
        val result = StatusResponseParser.parseBasalDeliveryPayload(data, validPumpTime)
        assertNotNull(result)
        assertTrue(result!!.isAutomated)
    }

    @Test
    fun `parseBasalDeliveryPayload with profile source not automated`() {
        val data = buildBasalData(sourceRaw = 1, commandedRate = 800)
        val result = StatusResponseParser.parseBasalDeliveryPayload(data, validPumpTime)
        assertNotNull(result)
        assertFalse(result!!.isAutomated)
    }

    @Test
    fun `parseBasalDeliveryPayload with excessive rate returns null`() {
        val data = buildBasalData(commandedRate = 16000) // 16 units/hr, over 15u limit
        val result = StatusResponseParser.parseBasalDeliveryPayload(data, validPumpTime)
        assertNull(result)
    }

    @Test
    fun `parseBasalDeliveryPayload with short payload returns null`() {
        val data = ByteArray(6) // too short (need 8)
        val result = StatusResponseParser.parseBasalDeliveryPayload(data, validPumpTime)
        assertNull(result)
    }

    // =======================================================================
    // Basal Extraction Tests
    // =======================================================================

    @Test
    fun `extractBasalFromHistoryLogs filters only event 279`() {
        val basalData = buildBasalData(commandedRate = 900)
        val records = listOf(
            makeRecord(1, 279, validPumpTime, basalData),
            makeRecord(2, 280, validPumpTime + 300, buildBolusData()),
            makeRecord(3, 399, validPumpTime + 600, ByteArray(16)),
        )
        val result = StatusResponseParser.extractBasalFromHistoryLogs(records)
        assertEquals(1, result.size)
        assertEquals(0.9f, result[0].rate, 0.001f)
    }

    @Test
    fun `extractBasalFromHistoryLogs returns sorted by timestamp`() {
        val basal1 = buildBasalData(commandedRate = 800)
        val basal2 = buildBasalData(commandedRate = 1200)
        val records = listOf(
            makeRecord(2, 279, validPumpTime + 300, basal2),
            makeRecord(1, 279, validPumpTime, basal1),
        )
        val result = StatusResponseParser.extractBasalFromHistoryLogs(records)
        assertEquals(2, result.size)
        assertEquals(0.8f, result[0].rate, 0.001f) // earlier timestamp first
        assertEquals(1.2f, result[1].rate, 0.001f)
    }

    @Test
    fun `extractBasalFromHistoryLogs empty for no event 279 records`() {
        val records = listOf(
            makeRecord(1, 280, validPumpTime, buildBolusData()),
            makeRecord(2, 399, validPumpTime + 300, ByteArray(16)),
        )
        val result = StatusResponseParser.extractBasalFromHistoryLogs(records)
        assertTrue(result.isEmpty())
    }

    // =======================================================================
    // Boundary Value Tests
    // =======================================================================

    @Test
    fun `parseBolusDeliveryPayload rejects max uint16 value with default limits`() {
        // uint16 max is 65535mu = 65.535u, exceeds default cap of 25u
        val data = buildBolusData(deliveredTotal = 65535)
        val result = StatusResponseParser.parseBolusDeliveryPayload(data, validPumpTime)
        assertNull(result)
    }

    @Test
    fun `parseBolusDeliveryPayload rejects uint16 max even with max allowed limits`() {
        // uint16 max is 65535mu = 65.535u, exceeds absolute ceiling of 25u
        val maxAllowed = SafetyLimits(maxBolusDoseMilliunits = SafetyLimits.ABSOLUTE_MAX_BOLUS_MILLIUNITS)
        val data = buildBolusData(deliveredTotal = 65535)
        val result = StatusResponseParser.parseBolusDeliveryPayload(data, validPumpTime, maxAllowed)
        assertNull(result)
    }

    @Test
    fun `parseBasalDeliveryPayload accepts 10 units per hr with custom limits`() {
        val limits = SafetyLimits(maxBasalRateMilliunits = 10_000)
        val data = buildBasalData(commandedRate = 10_000)
        val result = StatusResponseParser.parseBasalDeliveryPayload(data, validPumpTime, limits)
        assertNotNull(result)
        assertEquals(10.0f, result!!.rate, 0.001f)
    }

    @Test
    fun `parseBasalDeliveryPayload rejects just over custom limit`() {
        val limits = SafetyLimits(maxBasalRateMilliunits = 10_000)
        val data = buildBasalData(commandedRate = 10_001)
        val result = StatusResponseParser.parseBasalDeliveryPayload(data, validPumpTime, limits)
        assertNull(result)
    }

    @Test
    fun `parseBasalDeliveryPayload at MAX boundary accepts 15 units per hr`() {
        val data = buildBasalData(commandedRate = 15000)
        val result = StatusResponseParser.parseBasalDeliveryPayload(data, validPumpTime)
        assertNotNull(result)
        assertEquals(15.0f, result!!.rate, 0.001f)
    }

    @Test
    fun `parseBasalDeliveryPayload rejects just over MAX boundary`() {
        val data = buildBasalData(commandedRate = 15001)
        val result = StatusResponseParser.parseBasalDeliveryPayload(data, validPumpTime)
        assertNull(result)
    }

    // =======================================================================
    // TempRate Source Test
    // =======================================================================

    @Test
    fun `parseBasalDeliveryPayload with TempRate source is not automated`() {
        val data = buildBasalData(sourceRaw = 2, commandedRate = 1500)
        val result = StatusResponseParser.parseBasalDeliveryPayload(data, validPumpTime)
        assertNotNull(result)
        assertEquals(1.5f, result!!.rate, 0.001f)
        assertFalse(result.isAutomated) // TempRate (manual temp basal) is NOT automated
    }

    // =======================================================================
    // 18-byte Record Graceful Skip Tests
    // =======================================================================

    @Test
    fun `extractBolusesFromHistoryLogs skips records shorter than 26 bytes`() {
        // Build an 18-byte record (opcode 61 format) instead of 26-byte FFF8 format
        val shortRecord = ByteArray(18)
        val b64 = java.util.Base64.getEncoder().encodeToString(shortRecord)
        val records = listOf(
            HistoryLogRecord(
                sequenceNumber = 1,
                eventTypeId = 280,
                pumpTimeSeconds = validPumpTime,
                rawBytesB64 = b64,
            ),
        )
        val result = StatusResponseParser.extractBolusesFromHistoryLogs(records)
        assertTrue(result.isEmpty())
    }

    @Test
    fun `extractBasalFromHistoryLogs skips records shorter than 26 bytes`() {
        val shortRecord = ByteArray(18)
        val b64 = java.util.Base64.getEncoder().encodeToString(shortRecord)
        val records = listOf(
            HistoryLogRecord(
                sequenceNumber = 1,
                eventTypeId = 279,
                pumpTimeSeconds = validPumpTime,
                rawBytesB64 = b64,
            ),
        )
        val result = StatusResponseParser.extractBasalFromHistoryLogs(records)
        assertTrue(result.isEmpty())
    }

    // =======================================================================
    // Empty Input Tests
    // =======================================================================

    @Test
    fun `extractBolusesFromHistoryLogs with empty list returns empty`() {
        val result = StatusResponseParser.extractBolusesFromHistoryLogs(emptyList())
        assertTrue(result.isEmpty())
    }

    @Test
    fun `extractBasalFromHistoryLogs with empty list returns empty`() {
        val result = StatusResponseParser.extractBasalFromHistoryLogs(emptyList())
        assertTrue(result.isEmpty())
    }

    // =======================================================================
    // Offset Verification Tests
    // =======================================================================

    @Test
    fun `parseBasalDeliveryPayload reads commandedRate not profileRate`() {
        // profileRate=9999 at offset 4, commandedRate=800 at offset 6
        // If parser incorrectly reads offset 4, it would get 9.999 instead of 0.8
        val data = buildBasalData(profileRate = 9999, commandedRate = 800)
        val result = StatusResponseParser.parseBasalDeliveryPayload(data, validPumpTime)
        assertNotNull(result)
        assertEquals(0.8f, result!!.rate, 0.001f)
    }
}
