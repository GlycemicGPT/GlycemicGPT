package com.glycemicgpt.mobile.service

import com.glycemicgpt.mobile.data.local.GlucoseRangeStore
import com.glycemicgpt.mobile.data.local.dao.RawHistoryLogDao
import com.glycemicgpt.mobile.data.repository.PumpDataRepository
import com.glycemicgpt.mobile.data.repository.SyncQueueEnqueuer
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BatteryStatus
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.model.ControlIqMode
import com.glycemicgpt.mobile.domain.model.HistoryLogRecord
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.model.ReservoirReading
import com.glycemicgpt.mobile.domain.pump.HistoryLogParser
import com.glycemicgpt.mobile.domain.pump.PumpDriver
import com.glycemicgpt.mobile.wear.WearDataSender
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

@OptIn(ExperimentalCoroutinesApi::class)
class PumpPollingOrchestratorTest {

    private val connectionStateFlow = MutableStateFlow(ConnectionState.DISCONNECTED)
    private val pumpDriver = mockk<PumpDriver>(relaxed = true) {
        every { observeConnectionState() } returns connectionStateFlow
        coEvery { getIoB() } returns Result.success(
            IoBReading(iob = 2.5f, timestamp = Instant.now()),
        )
        coEvery { getBasalRate() } returns Result.success(
            BasalReading(
                rate = 0.8f,
                isAutomated = true,
                controlIqMode = ControlIqMode.STANDARD,
                timestamp = Instant.now(),
            ),
        )
        coEvery { getBatteryStatus() } returns Result.success(
            BatteryStatus(percentage = 80, isCharging = false, timestamp = Instant.now()),
        )
        coEvery { getReservoirLevel() } returns Result.success(
            ReservoirReading(unitsRemaining = 150f, timestamp = Instant.now()),
        )
        coEvery { getCgmStatus() } returns Result.success(
            CgmReading(glucoseMgDl = 120, trendArrow = CgmTrend.FLAT, timestamp = Instant.now()),
        )
        coEvery { getBolusHistory(any()) } returns Result.success(emptyList())
        coEvery { getHistoryLogs(any()) } returns Result.success(emptyList())
        coEvery { getPumpHardwareInfo() } returns Result.failure(RuntimeException("not connected"))
    }
    private val repository = mockk<PumpDataRepository>(relaxed = true) {
        coEvery { getLatestBolusTimestamp() } returns null
    }
    private val syncEnqueuer = mockk<SyncQueueEnqueuer>(relaxed = true)
    private val rawHistoryLogDao = mockk<RawHistoryLogDao>(relaxed = true)
    private val wearDataSender = mockk<WearDataSender>(relaxed = true)
    private val glucoseRangeStore = mockk<GlucoseRangeStore>(relaxed = true) {
        every { urgentLow } returns GlucoseRangeStore.DEFAULT_URGENT_LOW
        every { low } returns GlucoseRangeStore.DEFAULT_LOW
        every { high } returns GlucoseRangeStore.DEFAULT_HIGH
        every { urgentHigh } returns GlucoseRangeStore.DEFAULT_URGENT_HIGH
    }
    private val historyLogParser = mockk<HistoryLogParser>(relaxed = true)

    /**
     * Time to advance past the fast loop's initial delay + stagger + margin.
     * Fast loop fires at: INITIAL_DELAY + 0 + STAGGER + 0 + STAGGER (= 1500ms for CGM).
     * Second CGM: +INTERVAL_FAST + 2*STAGGER = 17500ms.
     * Tests that advance by SETTLE + INTERVAL_FAST need to reach the second CGM,
     * so we add extra margin (5 staggers) to ensure timing tests pass.
     */
    private val FAST_SETTLE_MS = PumpPollingOrchestrator.INITIAL_POLL_DELAY_MS +
        PumpPollingOrchestrator.REQUEST_STAGGER_MS * 5 + 100

    /**
     * Time to advance past ALL loop initial delays + staggers.
     * Uses the largest initial delay across all loops as the base.
     */
    private val ALL_SETTLE_MS = maxOf(
        PumpPollingOrchestrator.MEDIUM_LOOP_INITIAL_DELAY_MS,
        PumpPollingOrchestrator.SLOW_LOOP_INITIAL_DELAY_MS,
    ) + PumpPollingOrchestrator.REQUEST_STAGGER_MS * 4 + 100

    /** Alias for tests that only need fast loop data. */
    private val SETTLE_TIME_MS = FAST_SETTLE_MS

    private fun createOrchestrator() = PumpPollingOrchestrator(pumpDriver, repository, syncEnqueuer, rawHistoryLogDao, wearDataSender, glucoseRangeStore, historyLogParser)

    @Test
    fun `does not poll when disconnected`() = runTest {
        val orchestrator = createOrchestrator()
        orchestrator.start(this)

        advanceTimeBy(60_000)

        coVerify(exactly = 0) { pumpDriver.getIoB() }
        orchestrator.stop()
    }

    @Test
    fun `does not poll before initial delay elapses`() = runTest {
        val orchestrator = createOrchestrator()
        orchestrator.start(this)

        connectionStateFlow.value = ConnectionState.CONNECTED
        advanceTimeBy(100) // well before INITIAL_POLL_DELAY_MS

        coVerify(exactly = 0) { pumpDriver.getIoB() }
        coVerify(exactly = 0) { pumpDriver.getBasalRate() }
        coVerify(exactly = 0) { pumpDriver.getCgmStatus() }
        coVerify(exactly = 0) { pumpDriver.getBatteryStatus() }
        coVerify(exactly = 0) { pumpDriver.getReservoirLevel() }
        coVerify(exactly = 0) { pumpDriver.getBolusHistory(any()) }
        orchestrator.stop()
    }

    @Test
    fun `polls after initial delay when connected`() = runTest {
        val orchestrator = createOrchestrator()
        orchestrator.start(this)

        connectionStateFlow.value = ConnectionState.CONNECTED
        // Advance past ALL loop initial delays (medium loop takes 60s)
        advanceTimeBy(ALL_SETTLE_MS)

        coVerify(atLeast = 1) { pumpDriver.getIoB() }
        coVerify(atLeast = 1) { pumpDriver.getBasalRate() }
        coVerify(atLeast = 1) { pumpDriver.getBatteryStatus() }
        coVerify(atLeast = 1) { pumpDriver.getReservoirLevel() }
        coVerify(atLeast = 1) { pumpDriver.getBolusHistory(any()) }
        orchestrator.stop()
    }

    @Test
    fun `saves readings to repository on poll`() = runTest {
        val orchestrator = createOrchestrator()
        orchestrator.start(this)

        connectionStateFlow.value = ConnectionState.CONNECTED
        // Advance past ALL loop initial delays (medium loop takes 60s)
        advanceTimeBy(ALL_SETTLE_MS)

        coVerify(atLeast = 1) { repository.saveIoB(any()) }
        coVerify(atLeast = 1) { repository.saveBasal(any()) }
        coVerify(atLeast = 1) { repository.saveBattery(any()) }
        coVerify(atLeast = 1) { repository.saveReservoir(any()) }
        coVerify(atLeast = 1) { repository.saveCgm(any()) }
        orchestrator.stop()
    }

    @Test
    fun `polls IoB again after fast interval`() = runTest {
        val orchestrator = createOrchestrator()
        orchestrator.start(this)

        connectionStateFlow.value = ConnectionState.CONNECTED
        advanceTimeBy(SETTLE_TIME_MS) // initial poll (delay + stagger)
        coVerify(exactly = 1) { pumpDriver.getIoB() }

        advanceTimeBy(PumpPollingOrchestrator.INTERVAL_FAST_MS)
        coVerify(exactly = 2) { pumpDriver.getIoB() }
        orchestrator.stop()
    }

    @Test
    fun `stops polling on disconnect`() = runTest {
        val orchestrator = createOrchestrator()
        orchestrator.start(this)

        connectionStateFlow.value = ConnectionState.CONNECTED
        advanceTimeBy(SETTLE_TIME_MS)
        coVerify(exactly = 1) { pumpDriver.getIoB() }

        connectionStateFlow.value = ConnectionState.DISCONNECTED
        advanceTimeBy(PumpPollingOrchestrator.INTERVAL_FAST_MS + SETTLE_TIME_MS)
        // Should not have polled again after disconnect
        coVerify(exactly = 1) { pumpDriver.getIoB() }
        orchestrator.stop()
    }

    @Test
    fun `resumes polling on reconnect`() = runTest {
        val orchestrator = createOrchestrator()
        orchestrator.start(this)

        connectionStateFlow.value = ConnectionState.CONNECTED
        advanceTimeBy(SETTLE_TIME_MS)
        coVerify(exactly = 1) { pumpDriver.getIoB() }

        connectionStateFlow.value = ConnectionState.DISCONNECTED
        advanceTimeBy(1000)

        connectionStateFlow.value = ConnectionState.CONNECTED
        advanceTimeBy(SETTLE_TIME_MS)
        coVerify(exactly = 2) { pumpDriver.getIoB() }
        orchestrator.stop()
    }

    @Test
    fun `low battery multiplies poll interval`() = runTest {
        val orchestrator = createOrchestrator()
        orchestrator.phoneBatteryLow = true
        orchestrator.start(this)

        connectionStateFlow.value = ConnectionState.CONNECTED
        advanceTimeBy(SETTLE_TIME_MS)
        coVerify(exactly = 1) { pumpDriver.getIoB() }

        // Normal interval passes but should NOT trigger another poll
        advanceTimeBy(PumpPollingOrchestrator.INTERVAL_FAST_MS)
        coVerify(exactly = 1) { pumpDriver.getIoB() }

        // Full low-battery interval passes
        advanceTimeBy(
            PumpPollingOrchestrator.INTERVAL_FAST_MS *
                (PumpPollingOrchestrator.LOW_BATTERY_MULTIPLIER - 1),
        )
        coVerify(exactly = 2) { pumpDriver.getIoB() }
        orchestrator.stop()
    }

    @Test
    fun `polls CGM in fast loop when connected`() = runTest {
        val orchestrator = createOrchestrator()
        orchestrator.start(this)

        connectionStateFlow.value = ConnectionState.CONNECTED
        advanceTimeBy(SETTLE_TIME_MS) // initial poll
        coVerify(exactly = 1) { pumpDriver.getCgmStatus() }

        advanceTimeBy(PumpPollingOrchestrator.INTERVAL_FAST_MS)
        coVerify(exactly = 2) { pumpDriver.getCgmStatus() }
        orchestrator.stop()
    }

    @Test
    fun `phoneBatteryLow defaults to false`() {
        val orchestrator = createOrchestrator()
        assertFalse(orchestrator.phoneBatteryLow)
    }

    @Test
    fun `continues polling when individual read fails`() = runTest {
        coEvery { pumpDriver.getIoB() } returns Result.failure(RuntimeException("timeout"))
        val orchestrator = createOrchestrator()
        orchestrator.start(this)

        connectionStateFlow.value = ConnectionState.CONNECTED
        // Advance past ALL loop delays so battery/reservoir have also been polled
        advanceTimeBy(ALL_SETTLE_MS)

        // Other reads should still succeed
        coVerify(atLeast = 1) { repository.saveBasal(any()) }
        coVerify(atLeast = 1) { repository.saveBattery(any()) }

        // Should continue polling despite IoB failure
        advanceTimeBy(PumpPollingOrchestrator.INTERVAL_FAST_MS)
        coVerify(atLeast = 2) { pumpDriver.getIoB() }
        orchestrator.stop()
    }

    @Test
    fun `fast loop requests are staggered in order IoB then basal then CGM`() = runTest {
        val callOrder = mutableListOf<String>()
        coEvery { pumpDriver.getIoB() } coAnswers {
            callOrder.add("iob")
            Result.success(IoBReading(iob = 2.5f, timestamp = Instant.now()))
        }
        coEvery { pumpDriver.getBasalRate() } coAnswers {
            callOrder.add("basal")
            Result.success(BasalReading(rate = 0.8f, isAutomated = true, controlIqMode = ControlIqMode.STANDARD, timestamp = Instant.now()))
        }
        coEvery { pumpDriver.getCgmStatus() } coAnswers {
            callOrder.add("cgm")
            Result.success(CgmReading(glucoseMgDl = 120, trendArrow = CgmTrend.FLAT, timestamp = Instant.now()))
        }

        val orchestrator = createOrchestrator()
        orchestrator.start(this)

        connectionStateFlow.value = ConnectionState.CONNECTED
        advanceTimeBy(SETTLE_TIME_MS)

        // First 3 entries should be in stagger order
        assertTrue("Expected at least 3 calls, got ${callOrder.size}", callOrder.size >= 3)
        assertEquals("iob", callOrder[0])
        assertEquals("basal", callOrder[1])
        assertEquals("cgm", callOrder[2])
        orchestrator.stop()
    }

    // Alert threshold detection is now an instance method using GlucoseRangeStore.
    // We test it indirectly through watch alert sends (see below).

    @Test
    fun `alertLabel returns correct labels`() {
        assertEquals("URGENT LOW", PumpPollingOrchestrator.alertLabel("urgent_low"))
        assertEquals("URGENT HIGH", PumpPollingOrchestrator.alertLabel("urgent_high"))
        assertEquals("LOW", PumpPollingOrchestrator.alertLabel("low"))
        assertEquals("HIGH", PumpPollingOrchestrator.alertLabel("high"))
        assertEquals("", PumpPollingOrchestrator.alertLabel("unknown"))
    }

    @Test
    fun `sends alert to watch when threshold crossed`() = runTest {
        val orchestrator = createOrchestrator()
        orchestrator.start(this)

        connectionStateFlow.value = ConnectionState.CONNECTED
        advanceTimeBy(SETTLE_TIME_MS) // initial poll: 120 mg/dL = normal

        // No alert for normal reading
        coVerify(exactly = 0) { wearDataSender.sendAlert(any(), any(), any(), any()) }

        // Change to low reading
        coEvery { pumpDriver.getCgmStatus() } returns Result.success(
            CgmReading(glucoseMgDl = 65, trendArrow = CgmTrend.SINGLE_DOWN, timestamp = Instant.now()),
        )
        advanceTimeBy(PumpPollingOrchestrator.INTERVAL_FAST_MS)

        coVerify(exactly = 1) { wearDataSender.sendAlert("low", 65, any(), any()) }
        orchestrator.stop()
    }

    @Test
    fun `clears alert when returning to normal range`() = runTest {
        // Start with low reading
        coEvery { pumpDriver.getCgmStatus() } returns Result.success(
            CgmReading(glucoseMgDl = 65, trendArrow = CgmTrend.SINGLE_DOWN, timestamp = Instant.now()),
        )
        val orchestrator = createOrchestrator()
        orchestrator.start(this)

        connectionStateFlow.value = ConnectionState.CONNECTED
        advanceTimeBy(SETTLE_TIME_MS) // initial poll: low alert

        coVerify(exactly = 1) { wearDataSender.sendAlert("low", 65, any(), any()) }

        // Return to normal
        coEvery { pumpDriver.getCgmStatus() } returns Result.success(
            CgmReading(glucoseMgDl = 120, trendArrow = CgmTrend.FLAT, timestamp = Instant.now()),
        )
        advanceTimeBy(PumpPollingOrchestrator.INTERVAL_FAST_MS)

        coVerify(exactly = 1) { wearDataSender.clearAlert() }
        orchestrator.stop()
    }

    // -- Reconnection accelerated polling tests --------------------------------

    @Test
    fun `reconnection uses reduced medium loop delay`() = runTest {
        val orchestrator = createOrchestrator()
        orchestrator.start(this)

        // First connection
        connectionStateFlow.value = ConnectionState.CONNECTED
        advanceTimeBy(SETTLE_TIME_MS)
        coVerify(exactly = 1) { pumpDriver.getIoB() }

        // Disconnect
        connectionStateFlow.value = ConnectionState.DISCONNECTED
        advanceTimeBy(1000)

        // Reconnection: bolus history should fire within RECONNECT_MEDIUM_DELAY_MS (5s)
        // not MEDIUM_LOOP_INITIAL_DELAY_MS (60s)
        connectionStateFlow.value = ConnectionState.CONNECTED
        advanceTimeBy(PumpPollingOrchestrator.RECONNECT_MEDIUM_DELAY_MS + 100)
        coVerify(atLeast = 1) { pumpDriver.getBolusHistory(any()) }
        orchestrator.stop()
    }

    @Test
    fun `initial connection uses full medium loop delay`() = runTest {
        val orchestrator = createOrchestrator()
        orchestrator.start(this)

        // First connection -- should NOT poll bolus history before MEDIUM_LOOP_INITIAL_DELAY_MS
        connectionStateFlow.value = ConnectionState.CONNECTED
        advanceTimeBy(PumpPollingOrchestrator.RECONNECT_MEDIUM_DELAY_MS + 100)

        // At 5.1 seconds, bolus history should NOT have been polled (initial delay is 60s)
        coVerify(exactly = 0) { pumpDriver.getBolusHistory(any()) }
        orchestrator.stop()
    }

    @Test
    fun `reconnection uses reduced slow loop delay`() = runTest {
        val orchestrator = createOrchestrator()
        orchestrator.start(this)

        // First connection -- only settle briefly (not long enough for slow loop at 30s)
        connectionStateFlow.value = ConnectionState.CONNECTED
        advanceTimeBy(SETTLE_TIME_MS)

        // Disconnect
        connectionStateFlow.value = ConnectionState.DISCONNECTED
        advanceTimeBy(1000)

        // Reconnection: battery should fire within RECONNECT_SLOW_DELAY_MS (3s)
        // instead of SLOW_LOOP_INITIAL_DELAY_MS (30s)
        connectionStateFlow.value = ConnectionState.CONNECTED
        advanceTimeBy(PumpPollingOrchestrator.RECONNECT_SLOW_DELAY_MS + 100)
        coVerify(atLeast = 1) { pumpDriver.getBatteryStatus() }
        orchestrator.stop()
    }

    @Test
    fun `does not resend same alert type`() = runTest {
        coEvery { pumpDriver.getCgmStatus() } returns Result.success(
            CgmReading(glucoseMgDl = 200, trendArrow = CgmTrend.SINGLE_UP, timestamp = Instant.now()),
        )
        val orchestrator = createOrchestrator()
        orchestrator.start(this)

        connectionStateFlow.value = ConnectionState.CONNECTED
        advanceTimeBy(SETTLE_TIME_MS) // first high alert

        coVerify(exactly = 1) { wearDataSender.sendAlert("high", 200, any(), any()) }

        // Still high on next poll
        coEvery { pumpDriver.getCgmStatus() } returns Result.success(
            CgmReading(glucoseMgDl = 210, trendArrow = CgmTrend.SINGLE_UP, timestamp = Instant.now()),
        )
        advanceTimeBy(PumpPollingOrchestrator.INTERVAL_FAST_MS)

        // Should NOT send again for same type
        coVerify(exactly = 1) { wearDataSender.sendAlert(eq("high"), any(), any(), any()) }
        orchestrator.stop()
    }

    // -- HistoryLogParser integration tests ------------------------------------

    @Test
    fun `delegates history log extraction to HistoryLogParser`() = runTest {
        val fakeRecords = listOf(
            HistoryLogRecord(
                sequenceNumber = 100,
                rawBytesB64 = "dGVzdA==",
                eventTypeId = 399,
                pumpTimeSeconds = 572_000_000L,
            ),
        )
        coEvery { pumpDriver.getHistoryLogs(any()) } returns Result.success(fakeRecords)
        every { historyLogParser.extractCgmFromHistoryLogs(any(), any()) } returns emptyList()
        every { historyLogParser.extractBolusesFromHistoryLogs(any(), any()) } returns emptyList()
        every { historyLogParser.extractBasalFromHistoryLogs(any(), any()) } returns emptyList()

        val orchestrator = createOrchestrator()
        orchestrator.start(this)

        connectionStateFlow.value = ConnectionState.CONNECTED
        // Advance past slow loop initial delay so history logs get polled
        advanceTimeBy(ALL_SETTLE_MS)

        // Verify historyLogParser was called with the records from the driver
        verify(atLeast = 1) { historyLogParser.extractCgmFromHistoryLogs(fakeRecords, any()) }
        verify(atLeast = 1) { historyLogParser.extractBolusesFromHistoryLogs(fakeRecords, any()) }
        verify(atLeast = 1) { historyLogParser.extractBasalFromHistoryLogs(fakeRecords, any()) }
        orchestrator.stop()
    }
}
