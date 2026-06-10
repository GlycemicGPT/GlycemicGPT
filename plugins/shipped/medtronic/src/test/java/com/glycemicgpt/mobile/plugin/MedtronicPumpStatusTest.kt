/*
 * AC1: MedtronicPumpStatus forwards reads to the gateway, adapts Device Info onto PumpSettings /
 * PumpHardwareInfo, runs the pure extract* helpers, and routes pairing lifecycle to the manager.
 */
package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.ble.connection.MedtronicBleConnectionManager
import com.glycemicgpt.mobile.ble.messages.MedtronicHistoryParser
import com.glycemicgpt.mobile.ble.read.MedtronicDeviceInfo
import com.glycemicgpt.mobile.ble.read.MedtronicReadGateway
import com.glycemicgpt.mobile.domain.model.BatteryStatus
import com.glycemicgpt.mobile.domain.model.HistoryLogRecord
import com.glycemicgpt.mobile.domain.model.ReservoirReading
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneOffset

class MedtronicPumpStatusTest {

    private val gateway: MedtronicReadGateway = mockk(relaxed = true)
    private val connectionManager: MedtronicBleConnectionManager = mockk(relaxed = true)
    private val pumpStatus = MedtronicPumpStatus(gateway, connectionManager)

    private val deviceInfo = MedtronicDeviceInfo(
        modelNumber = "MMT-1880",
        serialNumber = "NG1234567H",
        hardwareRevision = "RevA",
        firmwareRevision = "4.2.1",
        softwareRevision = "10.5",
        systemId = "0011223344556677",
    )

    @Test
    fun `getBatteryStatus delegates to the gateway`() = runTest {
        val battery = BatteryStatus(percentage = 80, isCharging = false, timestamp = Instant.ofEpochSecond(1))
        coEvery { gateway.getBatteryStatus() } returns Result.success(battery)

        assertEquals(battery, pumpStatus.getBatteryStatus().getOrThrow())
        coVerify { gateway.getBatteryStatus() }
    }

    @Test
    fun `getReservoirLevel delegates to the gateway`() = runTest {
        val reservoir = ReservoirReading(unitsRemaining = 120f, timestamp = Instant.ofEpochSecond(1))
        coEvery { gateway.getReservoirLevel() } returns Result.success(reservoir)

        assertEquals(reservoir, pumpStatus.getReservoirLevel().getOrThrow())
        coVerify { gateway.getReservoirLevel() }
    }

    @Test
    fun `getPumpSettings maps the Device Information strings`() = runTest {
        coEvery { gateway.getDeviceInfo() } returns Result.success(deviceInfo)

        val settings = pumpStatus.getPumpSettings().getOrThrow()

        assertEquals("4.2.1", settings.firmwareVersion)
        assertEquals("NG1234567H", settings.serialNumber)
        assertEquals("MMT-1880", settings.modelNumber)
    }

    @Test
    fun `getPumpHardwareInfo adapts Device Info onto the shared shape`() = runTest {
        coEvery { gateway.getDeviceInfo() } returns Result.success(deviceInfo)

        val hw = pumpStatus.getPumpHardwareInfo().getOrThrow()

        assertEquals(1880L, hw.modelNumber)
        assertEquals(1234567L, hw.serialNumber)
        assertEquals("4.2.1", hw.pumpRev)
        assertEquals("RevA", hw.pcbaRev)
        assertTrue(hw.pumpFeatures.isEmpty())
    }

    @Test
    fun `getPumpSettings propagates a read failure`() = runTest {
        val failure = IllegalStateException("not connected")
        coEvery { gateway.getDeviceInfo() } returns Result.failure(failure)

        assertEquals(failure, pumpStatus.getPumpSettings().exceptionOrNull())
    }

    @Test
    fun `getHistoryLogs delegates to the gateway`() = runTest {
        coEvery { gateway.getHistoryLogs(7) } returns Result.success(emptyList())

        assertTrue(pumpStatus.getHistoryLogs(7).getOrThrow().isEmpty())
        coVerify { gateway.getHistoryLogs(7) }
    }

    @Test
    fun `extract helpers return empty for no records`() {
        val none = emptyList<HistoryLogRecord>()
        val limits = SafetyLimits()
        assertTrue(pumpStatus.extractCgmFromHistoryLogs(none, limits).isEmpty())
        assertTrue(pumpStatus.extractBolusesFromHistoryLogs(none, limits).isEmpty())
        assertTrue(pumpStatus.extractBasalFromHistoryLogs(none, limits).isEmpty())
    }

    @Test
    fun `extractCgmFromHistoryLogs actually routes raw records through the parser`() {
        // A reference-time record + one SG record (120 mg/dL at +300s) -- proves the delegate runs the
        // real MedtronicHistoryParser, not a stub that would also pass the empty-list case above.
        val reference = LocalDateTime.of(2026, 6, 1, 12, 0, 0).toInstant(ZoneOffset.UTC)
        val records = listOf(
            rawRecord(0xF00E, seq = 100, offsetSec = 0, bodyHex = "3cea0706010c0000"),
            rawRecord(0xF00C, seq = 101, offsetSec = 300, bodyHex = "0000780000000000"),
        )

        val cgm = pumpStatus.extractCgmFromHistoryLogs(records, SafetyLimits())

        assertEquals(1, cgm.size)
        assertEquals(120, cgm[0].glucoseMgDl)
        assertEquals(reference.plusSeconds(300), cgm[0].timestamp)
    }

    @Test
    fun `unpair routes to the connection manager`() {
        pumpStatus.unpair()
        verify { connectionManager.unpair() }
    }

    @Test
    fun `autoReconnectIfPaired routes to the connection manager`() {
        pumpStatus.autoReconnectIfPaired()
        verify { connectionManager.reconnectIfPaired() }
    }

    // -- IDD history record builders (documented layout: history_data.py; see MedtronicHistoryParserTest) --

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
