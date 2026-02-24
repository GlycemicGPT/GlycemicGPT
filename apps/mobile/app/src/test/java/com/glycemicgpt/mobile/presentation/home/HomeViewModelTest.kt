package com.glycemicgpt.mobile.presentation.home

import com.glycemicgpt.mobile.data.local.GlucoseRangeStore
import com.glycemicgpt.mobile.data.local.SafetyLimitsStore
import com.glycemicgpt.mobile.data.remote.GlycemicGptApi
import com.glycemicgpt.mobile.data.repository.AuthRepository
import com.glycemicgpt.mobile.data.remote.dto.GlucoseRangeResponse
import com.glycemicgpt.mobile.data.repository.PumpDataRepository
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BatteryStatus
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.model.ControlIqMode
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.model.ReservoirReading
import com.glycemicgpt.mobile.domain.model.TimeInRangeData
import com.glycemicgpt.mobile.domain.plugin.Plugin
import com.glycemicgpt.mobile.domain.pump.PumpDriver
import com.glycemicgpt.mobile.plugin.PluginRegistry
import com.glycemicgpt.mobile.service.BackendSyncManager
import com.glycemicgpt.mobile.service.SyncStatus
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import retrofit2.Response
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import java.time.Instant

@OptIn(ExperimentalCoroutinesApi::class)
class HomeViewModelTest {

    private val testDispatcher = UnconfinedTestDispatcher()

    private val connectionStateFlow = MutableStateFlow(ConnectionState.DISCONNECTED)
    private val iobFlow = MutableStateFlow<IoBReading?>(null)
    private val basalFlow = MutableStateFlow<BasalReading?>(null)
    private val batteryFlow = MutableStateFlow<BatteryStatus?>(null)
    private val reservoirFlow = MutableStateFlow<ReservoirReading?>(null)
    private val cgmFlow = MutableStateFlow<CgmReading?>(null)
    private val syncStatusFlow = MutableStateFlow(SyncStatus())

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
    }

    private val repository = mockk<PumpDataRepository>(relaxed = true) {
        every { observeLatestIoB() } returns iobFlow
        every { observeLatestBasal() } returns basalFlow
        every { observeLatestBattery() } returns batteryFlow
        every { observeLatestReservoir() } returns reservoirFlow
        every { observeLatestCgm() } returns cgmFlow
    }

    private val backendSyncManager = mockk<BackendSyncManager>(relaxed = true) {
        every { syncStatus } returns syncStatusFlow
    }

    private val glucoseRangeStore = mockk<GlucoseRangeStore>(relaxed = true) {
        every { urgentLow } returns GlucoseRangeStore.DEFAULT_URGENT_LOW
        every { low } returns GlucoseRangeStore.DEFAULT_LOW
        every { high } returns GlucoseRangeStore.DEFAULT_HIGH
        every { urgentHigh } returns GlucoseRangeStore.DEFAULT_URGENT_HIGH
        every { isStale(any()) } returns false
    }

    private val safetyLimitsStore = mockk<SafetyLimitsStore>(relaxed = true) {
        every { isStale(any()) } returns false
    }

    private val authRepository = mockk<AuthRepository>(relaxed = true)

    private val api = mockk<GlycemicGptApi>(relaxed = true)
    private val pluginRegistry = mockk<PluginRegistry>(relaxed = true) {
        every { allActivePlugins } returns MutableStateFlow<List<Plugin>>(emptyList())
    }

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun createViewModel() = HomeViewModel(pumpDriver, repository, backendSyncManager, glucoseRangeStore, safetyLimitsStore, authRepository, api, pluginRegistry)

    @Test
    fun `initial state has null readings and not refreshing`() = runTest {
        val vm = createViewModel()

        assertNull(vm.iob.value)
        assertNull(vm.basalRate.value)
        assertNull(vm.battery.value)
        assertNull(vm.reservoir.value)
        assertNull(vm.cgm.value)
        assertFalse(vm.isRefreshing.value)
        assertEquals(ConnectionState.DISCONNECTED, vm.connectionState.value)
    }

    @Test
    fun `cgm flow emits when repository updates`() = runTest {
        val vm = createViewModel()

        // Subscribe to activate WhileSubscribed stateIn
        val collected = mutableListOf<CgmReading?>()
        val job = backgroundScope.launch(testDispatcher) {
            vm.cgm.collect { collected.add(it) }
        }

        assertNull(vm.cgm.value)

        val reading = CgmReading(glucoseMgDl = 180, trendArrow = CgmTrend.SINGLE_UP, timestamp = Instant.now())
        cgmFlow.value = reading

        assertNotNull(vm.cgm.value)
        assertEquals(180, vm.cgm.value!!.glucoseMgDl)
        assertEquals(CgmTrend.SINGLE_UP, vm.cgm.value!!.trendArrow)

        job.cancel()
    }

    @Test
    fun `refreshData calls all pump driver methods including CGM`() = runTest {
        val vm = createViewModel()

        vm.refreshData()
        advanceUntilIdle()

        coVerify(atLeast = 1) { pumpDriver.getIoB() }
        coVerify(atLeast = 1) { pumpDriver.getBasalRate() }
        coVerify(atLeast = 1) { pumpDriver.getBatteryStatus() }
        coVerify(atLeast = 1) { pumpDriver.getReservoirLevel() }
        coVerify(atLeast = 1) { pumpDriver.getCgmStatus() }
    }

    @Test
    fun `refreshData saves CGM result to repository`() = runTest {
        val vm = createViewModel()

        vm.refreshData()
        advanceUntilIdle()

        coVerify(atLeast = 1) { repository.saveCgm(any()) }
    }

    @Test
    fun `refreshData sets isRefreshing to false when done`() = runTest {
        val vm = createViewModel()

        vm.refreshData()
        advanceUntilIdle()

        assertFalse(vm.isRefreshing.value)
    }

    @Test
    fun `refreshData resets isRefreshing on failure`() = runTest {
        coEvery { pumpDriver.getIoB() } throws RuntimeException("BLE error")
        val vm = createViewModel()

        vm.refreshData()
        advanceUntilIdle()

        assertFalse(vm.isRefreshing.value)
    }

    @Test
    fun `glucoseThresholds returns values from store`() {
        every { glucoseRangeStore.urgentLow } returns 50
        every { glucoseRangeStore.low } returns 65
        every { glucoseRangeStore.high } returns 200
        every { glucoseRangeStore.urgentHigh } returns 280
        val vm = createViewModel()
        val t = vm.glucoseThresholds.value
        assertEquals(50, t.urgentLow)
        assertEquals(65, t.low)
        assertEquals(200, t.high)
        assertEquals(280, t.urgentHigh)
    }

    @Test
    fun `connection state flows from pump driver`() = runTest {
        val vm = createViewModel()

        // Subscribe to activate WhileSubscribed stateIn
        val job = backgroundScope.launch(testDispatcher) {
            vm.connectionState.collect {}
        }

        assertEquals(ConnectionState.DISCONNECTED, vm.connectionState.value)

        connectionStateFlow.value = ConnectionState.CONNECTED
        assertEquals(ConnectionState.CONNECTED, vm.connectionState.value)

        job.cancel()
    }

    // -- Time in Range --------------------------------------------------------

    @Test
    fun `initial TIR period is 24 hours`() = runTest {
        val vm = createViewModel()
        assertEquals(TirPeriod.TWENTY_FOUR_HOURS, vm.selectedTirPeriod.value)
    }

    @Test
    fun `onTirPeriodSelected updates selected period`() = runTest {
        val vm = createViewModel()

        vm.onTirPeriodSelected(TirPeriod.THREE_DAYS)
        assertEquals(TirPeriod.THREE_DAYS, vm.selectedTirPeriod.value)

        vm.onTirPeriodSelected(TirPeriod.SEVEN_DAYS)
        assertEquals(TirPeriod.SEVEN_DAYS, vm.selectedTirPeriod.value)
    }

    @Test
    fun `timeInRange state flow emits repository data`() = runTest {
        val tirData = TimeInRangeData(
            lowPercent = 5f,
            inRangePercent = 80f,
            highPercent = 15f,
            totalReadings = 200,
        )
        every { repository.observeTimeInRange(any(), any(), any()) } returns flowOf(tirData)

        val vm = createViewModel()

        val job = backgroundScope.launch(testDispatcher) {
            vm.timeInRange.collect {}
        }

        advanceUntilIdle()

        val result = vm.timeInRange.value
        assertNotNull(result)
        assertEquals(80f, result!!.inRangePercent, 0.001f)
        assertEquals(200, result.totalReadings)

        job.cancel()
    }

    @Test
    fun `timeInRange recomputes when glucose thresholds change`() = runTest {
        val tirData = TimeInRangeData(
            lowPercent = 10f,
            inRangePercent = 60f,
            highPercent = 30f,
            totalReadings = 100,
        )
        every { repository.observeTimeInRange(any(), any(), any()) } returns flowOf(tirData)

        // Start with defaults (low=70, high=180)
        val vm = createViewModel()

        val job = backgroundScope.launch(testDispatcher) {
            vm.timeInRange.collect {}
        }
        advanceUntilIdle()

        // Verify initial subscription uses default thresholds
        verify { repository.observeTimeInRange(any(), eq(GlucoseRangeStore.DEFAULT_LOW), eq(GlucoseRangeStore.DEFAULT_HIGH)) }

        // Now simulate backend returning new thresholds via refreshData
        val rangeResponse = GlucoseRangeResponse(
            urgentLow = 60f,
            lowTarget = 90f,
            highTarget = 230f,
            urgentHigh = 330f,
        )
        coEvery { api.getGlucoseRange() } returns Response.success(rangeResponse)
        every { glucoseRangeStore.urgentLow } returns 60
        every { glucoseRangeStore.low } returns 90
        every { glucoseRangeStore.high } returns 230
        every { glucoseRangeStore.urgentHigh } returns 330

        vm.refreshData()
        advanceUntilIdle()

        // After threshold update, observeTimeInRange should be re-called with new low/high
        verify { repository.observeTimeInRange(any(), eq(90), eq(230)) }

        job.cancel()
    }

    // -- Glucose range sync ---------------------------------------------------

    @Test
    fun `refreshData updates glucose thresholds from API`() = runTest {
        val rangeResponse = GlucoseRangeResponse(
            urgentLow = 55f,
            lowTarget = 80f,
            highTarget = 200f,
            urgentHigh = 300f,
        )
        coEvery { api.getGlucoseRange() } returns Response.success(rangeResponse)
        every { glucoseRangeStore.urgentLow } returns 55
        every { glucoseRangeStore.low } returns 80
        every { glucoseRangeStore.high } returns 200
        every { glucoseRangeStore.urgentHigh } returns 300

        val vm = createViewModel()
        vm.refreshData()
        advanceUntilIdle()

        verify { glucoseRangeStore.updateAll(urgentLow = 55, low = 80, high = 200, urgentHigh = 300) }
        val t = vm.glucoseThresholds.value
        assertEquals(55, t.urgentLow)
        assertEquals(80, t.low)
        assertEquals(200, t.high)
        assertEquals(300, t.urgentHigh)
    }

    @Test
    fun `refreshGlucoseRange failure preserves existing thresholds`() = runTest {
        coEvery { api.getGlucoseRange() } throws RuntimeException("Network error")
        val vm = createViewModel()

        vm.refreshData()
        advanceUntilIdle()

        val t = vm.glucoseThresholds.value
        assertEquals(GlucoseRangeStore.DEFAULT_URGENT_LOW, t.urgentLow)
        assertEquals(GlucoseRangeStore.DEFAULT_LOW, t.low)
        assertEquals(GlucoseRangeStore.DEFAULT_HIGH, t.high)
        assertEquals(GlucoseRangeStore.DEFAULT_URGENT_HIGH, t.urgentHigh)
        assertFalse(vm.isRefreshing.value)
    }

    @Test
    fun `refreshGlucoseRange rejects inverted thresholds`() = runTest {
        val rangeResponse = GlucoseRangeResponse(
            urgentLow = 55f,
            lowTarget = 200f,
            highTarget = 80f,
            urgentHigh = 300f,
        )
        coEvery { api.getGlucoseRange() } returns Response.success(rangeResponse)

        val vm = createViewModel()
        vm.refreshData()
        advanceUntilIdle()

        // Store should NOT be updated because low >= high
        verify(exactly = 0) { glucoseRangeStore.updateAll(any(), any(), any(), any()) }
        // Thresholds should remain at defaults
        val t = vm.glucoseThresholds.value
        assertEquals(GlucoseRangeStore.DEFAULT_LOW, t.low)
        assertEquals(GlucoseRangeStore.DEFAULT_HIGH, t.high)
    }

    @Test
    fun `init refreshes glucose range when store is stale`() = runTest {
        every { glucoseRangeStore.isStale(any()) } returns true
        val rangeResponse = GlucoseRangeResponse(
            urgentLow = 60f,
            lowTarget = 85f,
            highTarget = 190f,
            urgentHigh = 290f,
        )
        coEvery { api.getGlucoseRange() } returns Response.success(rangeResponse)

        createViewModel()
        advanceUntilIdle()

        coVerify(atLeast = 1) { api.getGlucoseRange() }
        verify { glucoseRangeStore.updateAll(urgentLow = 60, low = 85, high = 190, urgentHigh = 290) }
    }

    @Test
    fun `init refreshes safety limits when store is stale`() = runTest {
        every { safetyLimitsStore.isStale(any()) } returns true
        createViewModel()
        advanceUntilIdle()
        coVerify(atLeast = 1) { authRepository.refreshSafetyLimits() }
    }
}
