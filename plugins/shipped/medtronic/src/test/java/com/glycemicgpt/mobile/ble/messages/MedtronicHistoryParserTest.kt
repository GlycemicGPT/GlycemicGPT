/*
 * AC2/AC3/AC4/AC5: the IDD history parser turns synthesized records into typed events + domain
 * models, preserves raw records for dedup/backfill, resolves absolute time from the reference-time
 * event, drops sentinel/out-of-range readings, and excludes SmartGuard micro-boluses (the flagged
 * nuance). Frames are synthesized to the documented record layout (history_data.py); no pump needed.
 */
package com.glycemicgpt.mobile.ble.messages

import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.model.HistoryLogRecord
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import java.time.LocalDateTime
import java.time.ZoneOffset
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MedtronicHistoryParserTest {

    private val reference = LocalDateTime.of(2026, 6, 1, 12, 0, 0).toInstant(ZoneOffset.UTC)

    // NGP_REFERENCE_TIME at seq 100: recording_reason 0x3c + datetime 2026-06-01 12:00:00 UTC.
    private val referenceRecord = record(0xF00E, 100, 0, "3c" + "ea07" + "06" + "01" + "0c" + "00" + "00")

    private fun record(typeId: Int, seq: Int, offsetSec: Int, bodyHex: String): HistoryLogRecord =
        MedtronicHistoryParser.toHistoryLogRecord(le16(typeId) + le32(seq) + le16(offsetSec) + hex(bodyHex), useE2e = false)!!

    @Test
    fun `toHistoryLogRecord preserves sequence, event type and relative offset`() {
        val raw = le16(0xF00C) + le32(101) + le16(300) + hex("0000780000000000")
        val log = MedtronicHistoryParser.toHistoryLogRecord(raw, useE2e = false)!!
        assertEquals(101, log.sequenceNumber)
        assertEquals(0xF00C, log.eventTypeId)
        assertEquals(300L, log.pumpTimeSeconds)
    }

    @Test
    fun `dedupBySequence keeps one record per sequence number`() {
        val a = record(0xF00C, 101, 300, "0000780000000000")
        val dup = record(0xF00C, 101, 300, "0000780000000000")
        val b = record(0xF00C, 102, 360, "0000820000000000")
        assertEquals(2, MedtronicHistoryParser.dedupBySequence(listOf(a, dup, b)).size)
    }

    @Test
    fun `extractCgm resolves absolute time and drops sentinels, out-of-range and pre-reference records`() {
        val records = listOf(
            referenceRecord,
            record(0xF00C, 50, 0, "0000820000000000"), // SG 130 BEFORE reference -> dropped
            record(0xF00C, 101, 300, "0000780000000000"), // SG 120 mg/dL at +300s
            record(0xF00C, 102, 360, "0000010300000000"), // sentinel 0x0301 -> dropped
            record(0xF00C, 103, 420, "0000580200000000"), // SG 600 mg/dL -> out of range, dropped
        )
        val cgm = MedtronicHistoryParser.extractCgmFromHistoryLogs(records)
        assertEquals(1, cgm.size)
        assertEquals(120, cgm[0].glucoseMgDl)
        assertEquals(CgmTrend.UNKNOWN, cgm[0].trendArrow)
        assertEquals(reference.plusSeconds(300), cgm[0].timestamp)
    }

    @Test
    fun `extractBoluses maps a delivered bolus as automated + correction and excludes micro-boluses`() {
        val records = listOf(
            referenceRecord,
            record(0x005A, 108, 0, "010033190000ff000000000000"), // programmed P1, id 1, fast 2.5
            record(0x0066, 109, 0, "08"), // programmed P2: delivery reason = correction
            record(0x0069, 110, 600, "010033190000ff000000000000"), // delivered P1, id 1, fast 2.5
            record(0x0096, 111, 600, "01000000005a"), // delivered P2: activation COMMANDED (auto)
            record(0xF001, 112, 660, "01010000ff"), // SmartGuard auto-basal micro-bolus -> excluded
        )
        val boluses = MedtronicHistoryParser.extractBolusesFromHistoryLogs(records)
        assertEquals(1, boluses.size)
        assertEquals(2.5f, boluses[0].units, 1e-4f)
        assertTrue(boluses[0].isAutomated)
        assertTrue(boluses[0].isCorrection)
        // Correction-only reason -> whole delivered amount attributed to correction, meal 0.
        assertEquals(2.5f, boluses[0].correctionUnits, 1e-4f)
        assertEquals(0f, boluses[0].mealUnits, 0f)
        assertEquals(reference.plusSeconds(600), boluses[0].timestamp)
    }

    @Test
    fun `extractBoluses rejects a bolus over the safety limit`() {
        // delivered P1: bolusId(2)=1, type(1)=0, fast f32 = 1e000000 (30 IU), extended(4)=0,
        // duration(2)=0 -> 13-byte body. 30000 mU > 25000 default cap, so it is dropped by the safety
        // gate (not by a parse/length failure).
        val records = listOf(
            referenceRecord,
            record(0x0069, 110, 600, "0100001e000000000000000000"),
        )
        assertTrue(MedtronicHistoryParser.extractBolusesFromHistoryLogs(records).isEmpty())
    }

    @Test
    fun `extractBasal maps the new rate and flags AP-controller delivery as automated`() {
        val records = listOf(
            referenceRecord,
            // flags 0x01 (context present), old 1.0, new 0.5 IU/h, context 0x55 (AP controller).
            record(0x0099, 120, 0, "01" + "0a0000ff" + "050000ff" + "55"),
        )
        val basal = MedtronicHistoryParser.extractBasalFromHistoryLogs(records)
        assertEquals(1, basal.size)
        assertEquals(0.5f, basal[0].rate, 1e-4f)
        assertTrue(basal[0].isAutomated)
    }

    @Test
    fun `extractBasal rejects a rate over the safety limit`() {
        val records = listOf(
            referenceRecord,
            // new rate 20 IU/h (0x00000014) -> 20000 mU/h > 15000 default cap.
            record(0x0099, 120, 0, "00" + "0a0000ff" + "14000000"),
        )
        assertTrue(MedtronicHistoryParser.extractBasalFromHistoryLogs(records).isEmpty())
    }

    @Test
    fun `parseRecordBody decodes a low-reservoir annunciation (cartridge event)`() {
        // event_flags 03, ann_id 0001, type 0xf069 (low reservoir), status 0x33, timestamp 0.
        val body = le16(0xF010) + le32(130) + le16(0) + hex("03" + "0100" + "69f0" + "33" + "00000000")
        val parsed = MedtronicHistoryParser.parseRecordBody(body)!!
        assertEquals(MedtronicHistoryEventType.ANNUNCIATION_CONSOLIDATED, parsed.eventType)
        val event = parsed.event as MedtronicHistoryEvent.Annunciation
        assertEquals(0x069, event.annunciationType)
    }

    @Test
    fun `parseRecordBody preserves an unrecognized event type as Unparsed`() {
        val body = le16(0x1234) + le32(140) + le16(0) + hex("deadbeef")
        val parsed = MedtronicHistoryParser.parseRecordBody(body)!!
        assertEquals(MedtronicHistoryEventType.UNDEFINED, parsed.eventType)
        assertEquals(MedtronicHistoryEvent.Unparsed, parsed.event)
    }

    private fun le16(v: Int): ByteArray = byteArrayOf((v and 0xFF).toByte(), ((v shr 8) and 0xFF).toByte())

    private fun le32(v: Int): ByteArray =
        byteArrayOf(
            (v and 0xFF).toByte(),
            ((v shr 8) and 0xFF).toByte(),
            ((v shr 16) and 0xFF).toByte(),
            ((v shr 24) and 0xFF).toByte(),
        )

    private fun hex(s: String): ByteArray {
        val clean = s.replace(" ", "")
        return ByteArray(clean.length / 2) { clean.substring(2 * it, 2 * it + 2).toInt(16).toByte() }
    }
}
