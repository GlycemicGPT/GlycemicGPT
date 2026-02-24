package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.domain.model.BatteryStatus
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.model.HistoryLogRecord
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import com.glycemicgpt.mobile.ble.connection.BleConnectionManager
import com.glycemicgpt.mobile.ble.connection.TandemBleDriver
import com.glycemicgpt.mobile.ble.messages.TandemHistoryLogParser
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

class TandemPumpStatusTest {

    private val bleDriver: TandemBleDriver = mockk(relaxed = true)
    private val historyParser: TandemHistoryLogParser = mockk(relaxed = true)
    private val connectionManager: BleConnectionManager = mockk(relaxed = true)

    private val pumpStatus = TandemPumpStatus(
        bleDriver = bleDriver,
        historyParser = historyParser,
        connectionManager = connectionManager,
    )

    @Test
    fun `getBatteryStatus delegates to bleDriver`() = runTest {
        val expected = BatteryStatus(
            percentage = 85,
            isCharging = false,
            timestamp = Instant.now(),
        )
        coEvery { bleDriver.getBatteryStatus() } returns Result.success(expected)

        val result = pumpStatus.getBatteryStatus()

        assertTrue(result.isSuccess)
        assertEquals(expected, result.getOrThrow())
        coVerify { bleDriver.getBatteryStatus() }
    }

    @Test
    fun `extractCgmFromHistoryLogs delegates to parser`() {
        val records = listOf(
            HistoryLogRecord(
                sequenceNumber = 100,
                rawBytesB64 = "AQID",
                eventTypeId = 399,
                pumpTimeSeconds = 5000L,
            ),
        )
        val limits = SafetyLimits()
        val expectedReadings = listOf(
            CgmReading(
                glucoseMgDl = 130,
                trendArrow = CgmTrend.SINGLE_UP,
                timestamp = Instant.now(),
            ),
        )
        every { historyParser.extractCgmFromHistoryLogs(records, limits) } returns expectedReadings

        val result = pumpStatus.extractCgmFromHistoryLogs(records, limits)

        assertEquals(1, result.size)
        assertEquals(130, result[0].glucoseMgDl)
        verify { historyParser.extractCgmFromHistoryLogs(records, limits) }
    }

    @Test
    fun `unpair delegates to connectionManager`() {
        pumpStatus.unpair()

        verify { connectionManager.unpair() }
    }
}
