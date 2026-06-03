/*
 * AC1: MedtronicInsulinSource forwards IOB / basal to the gateway, and builds bolus history by
 * extracting delivered boluses from the fetched raw records and filtering by the requested instant.
 */
package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.ble.messages.MedtronicHistoryParser
import com.glycemicgpt.mobile.ble.read.MedtronicReadGateway
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.HistoryLogRecord
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.model.PumpActivityMode
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneOffset

class MedtronicInsulinSourceTest {

    private val gateway: MedtronicReadGateway = mockk(relaxed = true)
    private val source = MedtronicInsulinSource(gateway)

    @Test
    fun `getIoB delegates to the gateway`() = runTest {
        val iob = IoBReading(iob = 1.2f, timestamp = Instant.ofEpochSecond(1_700_000_000))
        coEvery { gateway.getIoB() } returns Result.success(iob)

        assertEquals(iob, source.getIoB().getOrThrow())
        coVerify { gateway.getIoB() }
    }

    @Test
    fun `getBasalRate delegates to the gateway`() = runTest {
        val basal = BasalReading(
            rate = 0.8f,
            isAutomated = true,
            activityMode = PumpActivityMode.NONE,
            timestamp = Instant.ofEpochSecond(1_700_000_000),
        )
        coEvery { gateway.getBasalRate() } returns Result.success(basal)

        assertEquals(basal, source.getBasalRate().getOrThrow())
        coVerify { gateway.getBasalRate() }
    }

    @Test
    fun `the first bolus poll fetches from sequence 0`() = runTest {
        // No records -> no boluses; this asserts the wiring (the initial cursor is 0 + empty extraction),
        // not the parser internals (covered by MedtronicHistoryParserTest).
        coEvery { gateway.getHistoryLogs(0) } returns Result.success(emptyList())

        val result = source.getBolusHistory(Instant.ofEpochSecond(0), SafetyLimits())

        assertTrue(result.isSuccess)
        assertEquals(emptyList<Any>(), result.getOrThrow())
        coVerify { gateway.getHistoryLogs(0) }
    }

    @Test
    fun `bolus polling advances the sequence cursor so the next poll is incremental`() = runTest {
        // First poll returns records up to sequence 111; the cursor must advance there so the second
        // poll requests only newer records (the AC4 incremental cursor path) instead of rescanning the
        // full window from sequence 0.
        val reference = LocalDateTime.of(2026, 6, 1, 12, 0, 0).toInstant(ZoneOffset.UTC)
        val firstBatch = listOf(
            rawRecord(0xF00E, seq = 100, offsetSec = 0, bodyHex = "3cea0706010c0000"),
            rawRecord(0x0069, seq = 110, offsetSec = 600, bodyHex = "010033190000ff000000000000"),
            rawRecord(0x0096, seq = 111, offsetSec = 600, bodyHex = "01000000005a"),
        )
        coEvery { gateway.getHistoryLogs(0) } returns Result.success(firstBatch)
        coEvery { gateway.getHistoryLogs(111) } returns Result.success(emptyList())

        source.getBolusHistory(reference, SafetyLimits()).getOrThrow()
        val second = source.getBolusHistory(reference, SafetyLimits()).getOrThrow()

        assertTrue(second.isEmpty())
        coVerify(exactly = 1) { gateway.getHistoryLogs(0) }
        coVerify(exactly = 1) { gateway.getHistoryLogs(111) }
    }

    @Test
    fun `getBolusHistory propagates a history fetch failure`() = runTest {
        val failure = IllegalStateException("not connected")
        coEvery { gateway.getHistoryLogs(0) } returns Result.failure(failure)

        val result = source.getBolusHistory(Instant.ofEpochSecond(0), SafetyLimits())

        assertTrue(result.isFailure)
        assertEquals(failure, result.exceptionOrNull())
    }

    @Test
    fun `getBolusHistory extracts delivered boluses and filters by the since instant`() = runTest {
        // One delivered 2.5 IU bolus at reference + 600s, plus the reference-time anchor record.
        val reference = LocalDateTime.of(2026, 6, 1, 12, 0, 0).toInstant(ZoneOffset.UTC)
        val records = listOf(
            rawRecord(0xF00E, seq = 100, offsetSec = 0, bodyHex = "3cea0706010c0000"),
            rawRecord(0x0069, seq = 110, offsetSec = 600, bodyHex = "010033190000ff000000000000"),
            rawRecord(0x0096, seq = 111, offsetSec = 600, bodyHex = "01000000005a"),
        )
        coEvery { gateway.getHistoryLogs(0) } returns Result.success(records)

        // Fresh sources per assertion so each exercises the since filter from a clean cursor (the
        // incremental cursor advance is covered separately above).
        // since at the reference -> the bolus (at +600s) is included.
        val included = MedtronicInsulinSource(gateway).getBolusHistory(reference, SafetyLimits()).getOrThrow()
        assertEquals(1, included.size)
        assertEquals(2.5f, included[0].units, 1e-4f)

        // since after the bolus -> filtered out.
        val excluded = MedtronicInsulinSource(gateway)
            .getBolusHistory(reference.plusSeconds(601), SafetyLimits()).getOrThrow()
        assertTrue(excluded.isEmpty())
    }

    // -- IDD history record builder (documented layout: history_data.py; see MedtronicHistoryParserTest) --

    private fun rawRecord(typeId: Int, seq: Int, offsetSec: Int, bodyHex: String): HistoryLogRecord =
        MedtronicHistoryParser.toHistoryLogRecord(
            le16(typeId) + le32(seq) + le16(offsetSec) + hex(bodyHex),
            useE2e = false,
        )!!

    private fun le16(v: Int): ByteArray =
        byteArrayOf((v and 0xFF).toByte(), ((v shr 8) and 0xFF).toByte())

    private fun le32(v: Int): ByteArray = byteArrayOf(
        (v and 0xFF).toByte(),
        ((v shr 8) and 0xFF).toByte(),
        ((v shr 16) and 0xFF).toByte(),
        ((v shr 24) and 0xFF).toByte(),
    )

    private fun hex(s: String): ByteArray =
        ByteArray(s.length / 2) { i -> s.substring(2 * i, 2 * i + 2).toInt(16).toByte() }
}
