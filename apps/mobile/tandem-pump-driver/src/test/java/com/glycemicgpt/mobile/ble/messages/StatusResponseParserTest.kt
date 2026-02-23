package com.glycemicgpt.mobile.ble.messages

import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.model.ControlIqMode
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneOffset
import java.util.TimeZone

class StatusResponseParserTest {

    // -- IoB tests (opcode 109, 17-byte cargo) --------------------------------

    @Test
    fun `parseIoBResponse mudaliar mode (CIQ off)`() {
        // pumpX2 test vector: c00000007c380000f1000000a100000000
        val cargo = hexToBytes("c00000007c380000f1000000a100000000")
        val result = StatusResponseParser.parseIoBResponse(cargo)
        assertNotNull(result)
        // mudaliarIOB = 0xC0 = 192 milliunits = 0.192 U, iobType=0 -> use mudaliar
        assertEquals(0.192f, result!!.iob, 0.001f)
    }

    @Test
    fun `parseIoBResponse swan6hr mode (CIQ on)`() {
        // pumpX2 test vector: b80000008c370000f10000009a00000001
        val cargo = hexToBytes("b80000008c370000f10000009a00000001")
        val result = StatusResponseParser.parseIoBResponse(cargo)
        assertNotNull(result)
        // swan6hrIOB = 0x9A = 154 milliunits = 0.154 U, iobType=1 -> use swan
        assertEquals(0.154f, result!!.iob, 0.001f)
    }

    @Test
    fun `parseIoBResponse with typical values`() {
        // 2500 milliunits mudaliar, iobType=1 -> use swan6hr (1500 milliunits)
        val buf = ByteBuffer.allocate(17).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(2500) // mudaliarIOB
        buf.putInt(3600) // timeRemaining
        buf.putInt(3000) // mudaliarTotalIOB
        buf.putInt(1500) // swan6hrIOB
        buf.put(1)       // iobType = SWAN_6HR
        val result = StatusResponseParser.parseIoBResponse(buf.array())
        assertNotNull(result)
        assertEquals(1.5f, result!!.iob, 0.001f)
    }

    @Test
    fun `parseIoBResponse unknown iobType falls back to mudaliar`() {
        // iobType=2 (unknown future value) should fall back to mudaliar
        val buf = ByteBuffer.allocate(17).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(2500) // mudaliarIOB
        buf.putInt(3600) // timeRemaining
        buf.putInt(3000) // mudaliarTotalIOB
        buf.putInt(1500) // swan6hrIOB
        buf.put(2)       // iobType = unknown
        val result = StatusResponseParser.parseIoBResponse(buf.array())
        assertNotNull(result)
        // Falls back to mudaliar (2500 milliunits = 2.5 U)
        assertEquals(2.5f, result!!.iob, 0.001f)
    }

    @Test
    fun `parseIoBResponse returns null for short cargo`() {
        assertNull(StatusResponseParser.parseIoBResponse(ByteArray(16)))
    }

    @Test
    fun `parseIoBResponse returns null for empty cargo`() {
        assertNull(StatusResponseParser.parseIoBResponse(ByteArray(0)))
    }

    // -- Basal status tests (opcode 41, 9-byte cargo) -------------------------

    @Test
    fun `parseBasalStatusResponse normal delivery`() {
        // pumpX2 test vector: e8030000e803000000
        val cargo = hexToBytes("e8030000e803000000")
        val result = StatusResponseParser.parseBasalStatusResponse(cargo)
        assertNotNull(result)
        // currentBasalRate = 1000 milliunits/hr = 1.0 U/hr, modified=0
        assertEquals(1.0f, result!!.rate, 0.001f)
        assertFalse(result.isAutomated) // modified=0 means normal, not automated
    }

    @Test
    fun `parseBasalStatusResponse suspended or modified`() {
        // pumpX2 test vector: 200300000000000001
        val cargo = hexToBytes("200300000000000001")
        val result = StatusResponseParser.parseBasalStatusResponse(cargo)
        assertNotNull(result)
        // currentBasalRate = 0, modified=1 (suspended by CIQ)
        assertEquals(0.0f, result!!.rate, 0.001f)
        assertTrue(result.isAutomated) // modified=1
    }

    @Test
    fun `parseBasalStatusResponse with typical rate`() {
        val buf = ByteBuffer.allocate(9).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(800) // profileBasalRate = 0.8 U/hr
        buf.putInt(750) // currentBasalRate = 0.75 U/hr
        buf.put(0)      // not modified
        val result = StatusResponseParser.parseBasalStatusResponse(buf.array())
        assertNotNull(result)
        assertEquals(0.75f, result!!.rate, 0.001f)
        assertEquals(ControlIqMode.STANDARD, result.controlIqMode)
    }

    @Test
    fun `parseBasalStatusResponse returns null for short cargo`() {
        assertNull(StatusResponseParser.parseBasalStatusResponse(ByteArray(8)))
    }

    // -- Insulin status (reservoir) tests (opcode 37, 4-byte cargo) -----------

    @Test
    fun `parseInsulinStatusResponse whole units`() {
        // pumpX2 test vector: 00000023
        val cargo = hexToBytes("00000023")
        val result = StatusResponseParser.parseInsulinStatusResponse(cargo)
        assertNotNull(result)
        // uint16 LE at bytes 0-1 = 0x0000 = 0 units
        assertEquals(0f, result!!.unitsRemaining, 0.001f)
    }

    @Test
    fun `parseInsulinStatusResponse with 200 units`() {
        val buf = ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN)
        buf.putShort(200.toShort()) // 200 units (NOT milliunits)
        buf.put(0) // exact
        buf.put(35) // low threshold = 35 units
        val result = StatusResponseParser.parseInsulinStatusResponse(buf.array())
        assertNotNull(result)
        assertEquals(200f, result!!.unitsRemaining, 0.001f)
    }

    @Test
    fun `parseInsulinStatusResponse with 150 units`() {
        val buf = ByteBuffer.allocate(2).order(ByteOrder.LITTLE_ENDIAN)
        buf.putShort(150.toShort())
        val result = StatusResponseParser.parseInsulinStatusResponse(buf.array())
        assertNotNull(result)
        assertEquals(150f, result!!.unitsRemaining, 0.001f)
    }

    @Test
    fun `parseInsulinStatusResponse returns null for short cargo`() {
        assertNull(StatusResponseParser.parseInsulinStatusResponse(byteArrayOf(0x01)))
    }

    // -- Battery V1 tests (opcode 53, 2-byte cargo) ---------------------------

    @Test
    fun `parseBatteryV1Response with 100 percent`() {
        // pumpX2 test vector: 6364
        val cargo = hexToBytes("6364")
        val result = StatusResponseParser.parseBatteryV1Response(cargo)
        assertNotNull(result)
        // byte 1 (ibc) = 0x64 = 100%
        assertEquals(100, result!!.percentage)
        assertFalse(result.isCharging) // V1 has no charging flag
    }

    @Test
    fun `parseBatteryV1Response returns null for single byte`() {
        assertNull(StatusResponseParser.parseBatteryV1Response(byteArrayOf(42)))
    }

    // -- Battery V2 tests (opcode 145, 11-byte cargo) -------------------------

    @Test
    fun `parseBatteryV2Response not charging`() {
        // pumpX2 test vector: 1b0a000000000000000000 (11 bytes)
        val cargo = hexToBytes("1b0a000000000000000000")
        val result = StatusResponseParser.parseBatteryV2Response(cargo)
        assertNotNull(result)
        // byte 1 (ibc) = 0x0a = 10%, byte 2 = 0 (not charging)
        assertEquals(10, result!!.percentage)
        assertFalse(result.isCharging)
    }

    @Test
    fun `parseBatteryV2Response charging`() {
        // pumpX2 test vector: 1b0a010000000000000000 (11 bytes)
        val cargo = hexToBytes("1b0a010000000000000000")
        val result = StatusResponseParser.parseBatteryV2Response(cargo)
        assertNotNull(result)
        assertEquals(10, result!!.percentage)
        assertTrue(result.isCharging)
    }

    @Test
    fun `parseBatteryV2Response returns null for short cargo`() {
        assertNull(StatusResponseParser.parseBatteryV2Response(byteArrayOf(0x1b, 0x0a)))
    }

    // -- CGM EGV tests (opcode 35, 8-byte cargo) ------------------------------

    @Test
    fun `parseCgmEgvResponse with valid reading`() {
        // pumpX2 test vector: c87c131c7b000100
        val cargo = hexToBytes("c87c131c7b000100")
        val result = StatusResponseParser.parseCgmEgvResponse(cargo)
        assertNotNull(result)
        // glucose = 0x007B = 123 mg/dL, egvStatus = 1 (VALID)
        assertEquals(123, result!!.glucoseMgDl)
        assertEquals(CgmTrend.UNKNOWN, result.trendArrow) // trend comes from HomeScreenMirror
    }

    @Test
    fun `parseCgmEgvResponse accepts LOW status`() {
        // egvStatus = 2 (LOW) -- still has a valid glucose value
        val buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(471039176) // timestamp
        buf.putShort(55)      // 55 mg/dL (low but valid)
        buf.put(2)            // LOW
        buf.put(0)
        val result = StatusResponseParser.parseCgmEgvResponse(buf.array())
        assertNotNull(result)
        assertEquals(55, result!!.glucoseMgDl)
    }

    @Test
    fun `parseCgmEgvResponse accepts HIGH status`() {
        // egvStatus = 3 (HIGH) -- still has a valid glucose value
        val buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(471039176) // timestamp
        buf.putShort(350)     // 350 mg/dL (high but valid)
        buf.put(3)            // HIGH
        buf.put(0)
        val result = StatusResponseParser.parseCgmEgvResponse(buf.array())
        assertNotNull(result)
        assertEquals(350, result!!.glucoseMgDl)
    }

    @Test
    fun `parseCgmEgvResponse rejects INVALID status`() {
        // egvStatus = 0 (INVALID)
        val buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(471039176)
        buf.putShort(120)
        buf.put(0) // INVALID
        buf.put(0)
        assertNull(StatusResponseParser.parseCgmEgvResponse(buf.array()))
    }

    @Test
    fun `parseCgmEgvResponse with unavailable status returns null`() {
        // egvStatus = 4 (UNAVAILABLE)
        val cargo = hexToBytes("0000000000000400")
        assertNull(StatusResponseParser.parseCgmEgvResponse(cargo))
    }

    @Test
    fun `parseCgmEgvResponse with zero glucose returns null`() {
        val cargo = hexToBytes("c87c131c00000100")
        assertNull(StatusResponseParser.parseCgmEgvResponse(cargo))
    }

    @Test
    fun `parseCgmEgvResponse with glucose below 20 returns null`() {
        // Glucose values 1-19 are physiologically impossible and likely sensor noise
        val buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(471039176) // timestamp
        buf.putShort(19)      // 19 mg/dL (below minimum threshold)
        buf.put(1)            // VALID
        buf.put(0)            // trendRate
        assertNull(StatusResponseParser.parseCgmEgvResponse(buf.array()))
    }

    @Test
    fun `parseCgmEgvResponse accepts glucose at threshold 20`() {
        val buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(471039176) // timestamp
        buf.putShort(20)      // 20 mg/dL (minimum accepted value)
        buf.put(1)            // VALID
        buf.put(0)            // trendRate
        val result = StatusResponseParser.parseCgmEgvResponse(buf.array())
        assertNotNull(result)
        assertEquals(20, result!!.glucoseMgDl)
    }

    @Test
    fun `parseCgmEgvResponse with glucose over 500 returns null`() {
        // 501 = 0x01F5
        val buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(1000) // timestamp
        buf.putShort(501)
        buf.put(1) // VALID
        buf.put(0) // trendRate
        assertNull(StatusResponseParser.parseCgmEgvResponse(buf.array()))
    }

    @Test
    fun `parseCgmEgvResponse returns null for short cargo`() {
        assertNull(StatusResponseParser.parseCgmEgvResponse(ByteArray(7)))
    }

    @Test
    fun `parseCgmEgvResponse returns null for empty cargo`() {
        assertNull(StatusResponseParser.parseCgmEgvResponse(ByteArray(0)))
    }

    @Test
    fun `parseCgmEgvResponse converts local pump time to UTC in negative offset zone`() {
        // Pump time 471039176 + epoch 1199145600 = 1670184776
        // As local date-time: 2022-12-04T18:32:56
        // In America/New_York (UTC-5 in December): UTC = 2022-12-04T23:32:56 = 1670202776
        val savedTz = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("America/New_York"))
            val buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
            buf.putInt(471039176)
            buf.putShort(120)
            buf.put(1) // VALID
            buf.put(0)
            val result = StatusResponseParser.parseCgmEgvResponse(buf.array())
            assertNotNull(result)
            assertEquals(120, result!!.glucoseMgDl)
            assertEquals(1670202776L, result.timestamp.epochSecond)
        } finally {
            TimeZone.setDefault(savedTz)
        }
    }

    @Test
    fun `parseCgmEgvResponse converts local pump time to UTC in positive offset zone`() {
        // Same pump time, but in Europe/Berlin (UTC+1 in December)
        // Local 2022-12-04T18:32:56 CET = 2022-12-04T17:32:56 UTC = 1670181176
        val savedTz = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("Europe/Berlin"))
            val buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
            buf.putInt(471039176)
            buf.putShort(120)
            buf.put(1) // VALID
            buf.put(0)
            val result = StatusResponseParser.parseCgmEgvResponse(buf.array())
            assertNotNull(result)
            assertEquals(1670181176L, result!!.timestamp.epochSecond)
        } finally {
            TimeZone.setDefault(savedTz)
        }
    }

    @Test
    fun `parseCgmEgvResponse converts local pump time to UTC in UTC zone`() {
        // In UTC zone: local time IS UTC, so no offset applied
        // 471039176 + 1199145600 = 1670184776
        val savedTz = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("UTC"))
            val buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
            buf.putInt(471039176)
            buf.putShort(120)
            buf.put(1) // VALID
            buf.put(0)
            val result = StatusResponseParser.parseCgmEgvResponse(buf.array())
            assertNotNull(result)
            assertEquals(1670184776L, result!!.timestamp.epochSecond)
        } finally {
            TimeZone.setDefault(savedTz)
        }
    }

    // -- HomeScreenMirror tests (opcode 57, 9-byte cargo) ---------------------

    @Test
    fun `parseHomeScreenMirrorResponse with flat trend`() {
        val cargo = byteArrayOf(4, 0, 0, 0, 0, 0, 0, 0, 0) // trend=FLAT
        val result = StatusResponseParser.parseHomeScreenMirrorResponse(cargo)
        assertNotNull(result)
        assertEquals(CgmTrend.FLAT, result!!.trendArrow)
    }

    @Test
    fun `parseHomeScreenMirrorResponse maps all trend icons`() {
        val expected = mapOf(
            1 to CgmTrend.DOUBLE_UP,
            2 to CgmTrend.SINGLE_UP,
            3 to CgmTrend.FORTY_FIVE_UP,
            4 to CgmTrend.FLAT,
            5 to CgmTrend.FORTY_FIVE_DOWN,
            6 to CgmTrend.SINGLE_DOWN,
            7 to CgmTrend.DOUBLE_DOWN,
            0 to CgmTrend.UNKNOWN,
        )
        for ((iconId, expectedTrend) in expected) {
            val cargo = ByteArray(9)
            cargo[0] = iconId.toByte()
            val result = StatusResponseParser.parseHomeScreenMirrorResponse(cargo)
            assertNotNull("iconId $iconId should parse", result)
            assertEquals("iconId $iconId", expectedTrend, result!!.trendArrow)
        }
    }

    @Test
    fun `parseHomeScreenMirrorResponse reads CIQ state icons`() {
        val cargo = ByteArray(9)
        cargo[0] = 4 // FLAT trend
        cargo[5] = 6 // basalStatusIcon = increase_basal
        cargo[6] = 2 // apControlState = increase_basal (blue)
        val result = StatusResponseParser.parseHomeScreenMirrorResponse(cargo)
        assertNotNull(result)
        assertEquals(6, result!!.basalStatusIconId)
        assertEquals(2, result.apControlStateIconId)
    }

    @Test
    fun `parseHomeScreenMirrorResponse returns null for short cargo`() {
        assertNull(StatusResponseParser.parseHomeScreenMirrorResponse(ByteArray(6)))
    }

    // -- Pump settings tests (opcode 91) --------------------------------------

    @Test
    fun `parsePumpSettingsResponse with valid length-prefixed strings`() {
        val fw = "7.8.1".toByteArray()
        val serial = "SN12345678".toByteArray()
        val model = "t:slim X2".toByteArray()

        val buf = ByteBuffer.allocate(4 + fw.size + 4 + serial.size + 4 + model.size)
            .order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(fw.size).put(fw)
        buf.putInt(serial.size).put(serial)
        buf.putInt(model.size).put(model)

        val result = StatusResponseParser.parsePumpSettingsResponse(buf.array())
        assertNotNull(result)
        assertEquals("7.8.1", result!!.firmwareVersion)
        assertEquals("SN12345678", result.serialNumber)
        assertEquals("t:slim X2", result.modelNumber)
    }

    @Test
    fun `parsePumpSettingsResponse returns null for truncated data`() {
        assertNull(StatusResponseParser.parsePumpSettingsResponse(byteArrayOf(0x05, 0x00)))
    }

    // -- Last bolus status tests (opcode 49) -----------------------------------

    @Test
    fun `parseLastBolusStatusResponse with completed bolus`() {
        // 17-byte LastBolusStatusResponse
        // Use a fixed timezone so pump time construction is deterministic
        val savedTz = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("America/Chicago"))
            // Construct a pump time representing "10 minutes ago" in local time
            val tenMinAgoLocal = LocalDateTime.now().minusMinutes(10)
            val recentPumpTime = (tenMinAgoLocal.toEpochSecond(ZoneOffset.UTC) - 1199145600L).toInt()
            val buf = ByteBuffer.allocate(17).order(ByteOrder.LITTLE_ENDIAN)
            buf.putInt(42)             // bolusId
            buf.putInt(recentPumpTime) // timestamp (Tandem epoch, local time)
            buf.putInt(3500)           // deliveredVolume (milliunits = 3.5 units)
            buf.put(3)                 // bolusStatusId = COMPLETED
            buf.put(1)                 // bolusSourceId = AUTO_PILOT
            buf.put(0x09.toByte())     // bolusTypeBitmask = STANDARD | CORRECTION
            buf.putShort(0)            // extendedBolusDuration

            val since = Instant.now().minusSeconds(3600)
            val events = StatusResponseParser.parseLastBolusStatusResponse(buf.array(), since)
            assertEquals(1, events.size)
            assertEquals(3.5f, events[0].units, 0.001f)
            assertTrue(events[0].isAutomated) // AUTO_PILOT
            assertTrue(events[0].isCorrection) // bitmask bit 3
        } finally {
            TimeZone.setDefault(savedTz)
        }
    }

    @Test
    fun `parseLastBolusStatusResponse returns empty for canceled bolus`() {
        val savedTz = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("America/Chicago"))
            val oneMinAgoLocal = LocalDateTime.now().minusMinutes(1)
            val recentPumpTime = (oneMinAgoLocal.toEpochSecond(ZoneOffset.UTC) - 1199145600L).toInt()
            val buf = ByteBuffer.allocate(17).order(ByteOrder.LITTLE_ENDIAN)
            buf.putInt(43)             // bolusId
            buf.putInt(recentPumpTime) // timestamp (local time)
            buf.putInt(1000)           // deliveredVolume
            buf.put(2)                 // bolusStatusId = CANCELED
            buf.put(0)                 // bolusSourceId = GUI
            buf.put(1)                 // bolusTypeBitmask = STANDARD
            buf.putShort(0)

            val since = Instant.now().minusSeconds(3600)
            val events = StatusResponseParser.parseLastBolusStatusResponse(buf.array(), since)
            assertTrue(events.isEmpty())
        } finally {
            TimeZone.setDefault(savedTz)
        }
    }

    @Test
    fun `parseLastBolusStatusResponse V2 20-byte cargo with prefix byte`() {
        // V2/extended format: 1-byte prefix + 17-byte V1 fields + 2-byte extension
        val savedTz = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("America/Chicago"))
            val tenMinAgoLocal = LocalDateTime.now().minusMinutes(10)
            val recentPumpTime = (tenMinAgoLocal.toEpochSecond(ZoneOffset.UTC) - 1199145600L).toInt()
            val buf = ByteBuffer.allocate(20).order(ByteOrder.LITTLE_ENDIAN)
            buf.put(0x01)              // V2 status prefix
            buf.putInt(5249)           // bolusId
            buf.putInt(recentPumpTime) // timestamp
            buf.putInt(2060)           // deliveredVolume (milliunits = 2.06 units)
            buf.put(3)                 // bolusStatusId = COMPLETED
            buf.put(0)                 // bolusSourceId = GUI (manual)
            buf.put(0x09.toByte())     // bolusTypeBitmask = STANDARD | CORRECTION
            buf.putShort(0)            // extendedBolusDuration
            buf.put(0)                 // V2 extension byte

            val since = Instant.now().minusSeconds(3600)
            val events = StatusResponseParser.parseLastBolusStatusResponse(buf.array(), since)
            assertEquals(1, events.size)
            assertEquals(2.06f, events[0].units, 0.01f)
            assertFalse(events[0].isAutomated) // GUI = manual
            assertTrue(events[0].isCorrection) // bitmask bit 3
        } finally {
            TimeZone.setDefault(savedTz)
        }
    }

    @Test
    fun `parseLastBolusStatusResponse V2 auto-pilot correction`() {
        val savedTz = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("America/Chicago"))
            val fiveMinAgoLocal = LocalDateTime.now().minusMinutes(5)
            val recentPumpTime = (fiveMinAgoLocal.toEpochSecond(ZoneOffset.UTC) - 1199145600L).toInt()
            val buf = ByteBuffer.allocate(20).order(ByteOrder.LITTLE_ENDIAN)
            buf.put(0x01)              // V2 status prefix
            buf.putInt(5250)           // bolusId
            buf.putInt(recentPumpTime) // timestamp
            buf.putInt(1500)           // deliveredVolume (1.5 units)
            buf.put(3)                 // bolusStatusId = COMPLETED
            buf.put(1)                 // bolusSourceId = AUTO_PILOT
            buf.put(0x08.toByte())     // bolusTypeBitmask = CORRECTION only
            buf.putShort(0)            // extendedBolusDuration
            buf.put(0)                 // V2 extension byte

            val since = Instant.now().minusSeconds(3600)
            val events = StatusResponseParser.parseLastBolusStatusResponse(buf.array(), since)
            assertEquals(1, events.size)
            assertEquals(1.5f, events[0].units, 0.001f)
            assertTrue(events[0].isAutomated) // AUTO_PILOT
            assertTrue(events[0].isCorrection) // bitmask bit 3
        } finally {
            TimeZone.setDefault(savedTz)
        }
    }

    @Test
    fun `parseLastBolusStatusResponse V2 canceled bolus returns empty`() {
        val savedTz = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("America/Chicago"))
            val oneMinAgoLocal = LocalDateTime.now().minusMinutes(1)
            val recentPumpTime = (oneMinAgoLocal.toEpochSecond(ZoneOffset.UTC) - 1199145600L).toInt()
            val buf = ByteBuffer.allocate(20).order(ByteOrder.LITTLE_ENDIAN)
            buf.put(0x01)              // V2 status prefix
            buf.putInt(5251)           // bolusId
            buf.putInt(recentPumpTime) // timestamp
            buf.putInt(2000)           // deliveredVolume
            buf.put(2)                 // bolusStatusId = CANCELED
            buf.put(0)                 // bolusSourceId = GUI
            buf.put(0x01)              // bolusTypeBitmask = STANDARD
            buf.putShort(0)
            buf.put(0)

            val since = Instant.now().minusSeconds(3600)
            val events = StatusResponseParser.parseLastBolusStatusResponse(buf.array(), since)
            assertTrue(events.isEmpty())
        } finally {
            TimeZone.setDefault(savedTz)
        }
    }

    @Test
    fun `parseLastBolusStatusResponse rejects 18-byte cargo as invalid`() {
        // 18 bytes is neither V1 (17) nor V2 (20+) -- should be rejected
        val cargo = ByteArray(18)
        assertTrue(
            StatusResponseParser.parseLastBolusStatusResponse(cargo, Instant.now()).isEmpty(),
        )
    }

    @Test
    fun `parseLastBolusStatusResponse rejects 19-byte cargo as invalid`() {
        val cargo = ByteArray(19)
        assertTrue(
            StatusResponseParser.parseLastBolusStatusResponse(cargo, Instant.now()).isEmpty(),
        )
    }

    @Test
    fun `parseLastBolusStatusResponse returns empty for short cargo`() {
        assertTrue(
            StatusResponseParser.parseLastBolusStatusResponse(byteArrayOf(0x01, 0x02), Instant.now()).isEmpty(),
        )
    }

    // -- PumpVersion tests (opcode 85, 48-byte cargo) -------------------------

    @Test
    fun `parsePumpVersionResponse tslim X2 test vector`() {
        // Values from pumpX2 PumpVersionResponseTest
        val buf = ByteBuffer.allocate(48).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(105900)     // armSwVer
        buf.putInt(105900)     // mspSwVer
        buf.putInt(0)          // configABits
        buf.putInt(0)          // configBBits
        buf.putInt(90556643)   // serialNum
        buf.putInt(1005279)    // partNum
        buf.put("0\u0000\u0000\u0000\u0000\u0000\u0000\u0000".toByteArray(Charsets.UTF_8)) // pumpRev (8 bytes)
        buf.putInt(1088111696) // pcbaSN
        buf.put("A\u0000\u0000\u0000\u0000\u0000\u0000\u0000".toByteArray(Charsets.UTF_8)) // pcbaRev (8 bytes)
        buf.putInt(1000354)    // modelNum

        val result = StatusResponseParser.parsePumpVersionResponse(buf.array())
        assertNotNull(result)
        assertEquals(105900L, result!!.armSwVer)
        assertEquals(105900L, result.mspSwVer)
        assertEquals(0L, result.configABits)
        assertEquals(0L, result.configBBits)
        assertEquals(90556643L, result.serialNumber)
        assertEquals(1005279L, result.partNumber)
        assertEquals("0", result.pumpRev)
        assertEquals(1088111696L, result.pcbaSn)
        assertEquals("A", result.pcbaRev)
        assertEquals(1000354L, result.modelNumber)
        assertTrue(result.pumpFeatures.isEmpty())
    }

    @Test
    fun `parsePumpVersionResponse Mobi test vector`() {
        // Values from pumpX2 PumpVersionResponseTest (Mobi)
        val buf = ByteBuffer.allocate(48).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt((-666269539).toInt()) // armSwVer = 3628697757 as uint32 (overflows signed int)
        buf.putInt(0)          // mspSwVer
        buf.putInt(0)          // configABits
        buf.putInt(0)          // configBBits
        buf.putInt(1226976)    // serialNum
        buf.putInt(1013045)    // partNum
        buf.put("0\u0000\u0000\u0000\u0000\u0000\u0000\u0000".toByteArray(Charsets.UTF_8))
        buf.putInt(232700077)  // pcbaSN
        buf.put("0\u0000\u0000\u0000\u0000\u0000\u0000\u0000".toByteArray(Charsets.UTF_8))
        buf.putInt(1004000)    // modelNum

        val result = StatusResponseParser.parsePumpVersionResponse(buf.array())
        assertNotNull(result)
        assertEquals(3628697757L, result!!.armSwVer)
        assertEquals(0L, result.mspSwVer)
        assertEquals(1226976L, result.serialNumber)
        assertEquals(1013045L, result.partNumber)
        assertEquals("0", result.pumpRev)
        assertEquals(232700077L, result.pcbaSn)
        assertEquals("0", result.pcbaRev)
        assertEquals(1004000L, result.modelNumber)
    }

    @Test
    fun `parsePumpVersionResponse returns null for short cargo`() {
        assertNull(StatusResponseParser.parsePumpVersionResponse(ByteArray(47)))
    }

    @Test
    fun `parsePumpVersionResponse returns null for empty cargo`() {
        assertNull(StatusResponseParser.parsePumpVersionResponse(ByteArray(0)))
    }

    // -- HistoryLogStatusResponse tests (opcode 59, 12-byte cargo) ---------------

    @Test
    fun `parseHistoryLogStatusResponse with valid range`() {
        val buf = ByteBuffer.allocate(12).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(401) // numEntries (lastSeq - firstSeq + 1 = 500 - 100 + 1)
        buf.putInt(100) // firstSeq
        buf.putInt(500) // lastSeq
        val result = StatusResponseParser.parseHistoryLogStatusResponse(buf.array())
        assertNotNull(result)
        assertEquals(100, result!!.firstSeq)
        assertEquals(500, result.lastSeq)
    }

    @Test
    fun `parseHistoryLogStatusResponse with zero range`() {
        val buf = ByteBuffer.allocate(12).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(0) // numEntries
        buf.putInt(0) // firstSeq
        buf.putInt(0) // lastSeq
        val result = StatusResponseParser.parseHistoryLogStatusResponse(buf.array())
        assertNotNull(result)
        assertEquals(0, result!!.firstSeq)
        assertEquals(0, result.lastSeq)
    }

    @Test
    fun `parseHistoryLogStatusResponse returns null for short cargo`() {
        assertNull(StatusResponseParser.parseHistoryLogStatusResponse(ByteArray(11)))
    }

    @Test
    fun `parseHistoryLogStatusResponse returns null for empty cargo`() {
        assertNull(StatusResponseParser.parseHistoryLogStatusResponse(ByteArray(0)))
    }

    @Test
    fun `parseHistoryLogStatusResponse ignores extra bytes`() {
        val buf = ByteBuffer.allocate(16).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(90) // numEntries
        buf.putInt(10) // firstSeq
        buf.putInt(99) // lastSeq
        buf.putInt(42) // extra garbage
        val result = StatusResponseParser.parseHistoryLogStatusResponse(buf.array())
        assertNotNull(result)
        assertEquals(10, result!!.firstSeq)
        assertEquals(99, result.lastSeq)
    }

    @Test
    fun `parseHistoryLogStatusResponse with real pump data`() {
        // Real pump response: 8c 97 04 00 00 20 0f 00 8b b7 13 00
        val cargo = byteArrayOf(
            0x8c.toByte(), 0x97.toByte(), 0x04, 0x00, // numEntries = 300940
            0x00, 0x20, 0x0f, 0x00,                   // firstSeq = 991232
            0x8b.toByte(), 0xb7.toByte(), 0x13, 0x00,  // lastSeq = 1292171
        )
        val result = StatusResponseParser.parseHistoryLogStatusResponse(cargo)
        assertNotNull(result)
        assertEquals(991232, result!!.firstSeq)
        assertEquals(1292171, result.lastSeq)
    }

    // -- HistoryLogResponse tests (opcode 61, N x 18-byte records) ------------
    // NOTE: parseHistoryLogResponse uses android.util.Base64 internally,
    // which is not available in JVM unit tests. Edge-case tests (short cargo,
    // empty cargo) that return before hitting Base64 are kept here. Full
    // record parsing is covered by on-device instrumented tests.

    @Test
    fun `parseHistoryLogResponse returns empty for short cargo`() {
        assertTrue(StatusResponseParser.parseHistoryLogResponse(ByteArray(17), sinceSequence = 0).isEmpty())
    }

    @Test
    fun `parseHistoryLogResponse returns empty for empty cargo`() {
        assertTrue(StatusResponseParser.parseHistoryLogResponse(ByteArray(0), sinceSequence = 0).isEmpty())
    }

    // -- PumpFeatures tests (opcode 79, 8-byte cargo) -------------------------

    @Test
    fun `parsePumpFeaturesResponse with controlIQ and dexcomG6 and basalIQ`() {
        // Bits: 0=dexcomG5, 1=dexcomG6, 2=basalIQ, 10=controlIQ
        // Set bits 1, 2, 10 = (1 shl 1) or (1 shl 2) or (1 shl 10) = 1030
        val buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
        buf.putLong(1030L)
        val result = StatusResponseParser.parsePumpFeaturesResponse(buf.array())
        assertFalse(result["dexcomG5"]!!)
        assertTrue(result["dexcomG6"]!!)
        assertTrue(result["basalIQ"]!!)
        assertTrue(result["controlIQ"]!!)
    }

    @Test
    fun `parsePumpFeaturesResponse with zero bitmask`() {
        val result = StatusResponseParser.parsePumpFeaturesResponse(ByteArray(8))
        assertEquals(4, result.size)
        assertFalse(result["dexcomG5"]!!)
        assertFalse(result["dexcomG6"]!!)
        assertFalse(result["basalIQ"]!!)
        assertFalse(result["controlIQ"]!!)
    }

    @Test
    fun `parsePumpFeaturesResponse returns empty map for short cargo`() {
        assertTrue(StatusResponseParser.parsePumpFeaturesResponse(ByteArray(7)).isEmpty())
    }

    // -- Helper ---------------------------------------------------------------

    private fun hexToBytes(hex: String): ByteArray {
        val len = hex.length
        val data = ByteArray(len / 2)
        var i = 0
        while (i < len) {
            data[i / 2] = ((Character.digit(hex[i], 16) shl 4) + Character.digit(hex[i + 1], 16)).toByte()
            i += 2
        }
        return data
    }
}
