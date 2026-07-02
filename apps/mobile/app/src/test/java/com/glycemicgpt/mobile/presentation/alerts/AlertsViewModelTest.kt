package com.glycemicgpt.mobile.presentation.alerts

import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.local.entity.AlertEntity
import com.glycemicgpt.mobile.data.network.NetworkMonitor
import com.glycemicgpt.mobile.data.network.NetworkStatus
import com.glycemicgpt.mobile.data.repository.AlertRepository
import com.glycemicgpt.mobile.domain.model.GlucoseUnit
import com.glycemicgpt.mobile.service.AlertNotificationManager
import com.glycemicgpt.mobile.service.AlertStreamStateHolder
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
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
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class AlertsViewModelTest {

    private val testDispatcher = UnconfinedTestDispatcher()
    private val alertsFlow = MutableStateFlow<List<AlertEntity>>(emptyList())
    private val networkStatusFlow = MutableStateFlow(NetworkStatus.REACHABLE)
    private lateinit var repository: AlertRepository
    private lateinit var notificationManager: AlertNotificationManager
    private lateinit var appSettingsStore: AppSettingsStore
    private lateinit var networkMonitor: NetworkMonitor
    private lateinit var alertStreamStateHolder: AlertStreamStateHolder

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
        repository = mockk(relaxed = true) {
            every { observeRecentAlerts() } returns alertsFlow
            coEvery { fetchPendingAlerts() } returns Result.success(emptyList())
        }
        notificationManager = mockk(relaxed = true)
        appSettingsStore = mockk(relaxed = true) {
            every { glucoseUnit } returns GlucoseUnit.MGDL
            every { glucoseUnitFlow() } returns flowOf(GlucoseUnit.MGDL)
        }
        networkMonitor = mockk(relaxed = true) {
            every { status } returns networkStatusFlow
        }
        alertStreamStateHolder = AlertStreamStateHolder()
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun createViewModel() = AlertsViewModel(
        repository,
        notificationManager,
        appSettingsStore,
        networkMonitor,
        alertStreamStateHolder,
    )

    private fun makeAlert(
        serverId: String = "alert-1",
        severity: String = "warning",
        currentValue: Double = 250.0,
        acknowledged: Boolean = false,
    ) = AlertEntity(
        serverId = serverId,
        alertType = "high_warning",
        severity = severity,
        message = "High glucose warning",
        currentValue = currentValue,
        timestampMs = System.currentTimeMillis(),
        acknowledged = acknowledged,
    )

    @Test
    fun `initial state is not loading with no error`() = runTest {
        val vm = createViewModel()
        advanceUntilIdle()

        assertFalse(vm.uiState.value.isLoading)
        assertNull(vm.uiState.value.error)
    }

    @Test
    fun `alerts flow emits when repository updates`() = runTest {
        val vm = createViewModel()
        advanceUntilIdle()

        val collected = mutableListOf<List<AlertEntity>>()
        val job = backgroundScope.launch(testDispatcher) {
            vm.alerts.collect { collected.add(it) }
        }

        assertTrue(vm.alerts.value.isEmpty())

        val alert = makeAlert()
        alertsFlow.value = listOf(alert)

        assertEquals(1, vm.alerts.value.size)
        assertEquals("alert-1", vm.alerts.value[0].serverId)

        job.cancel()
    }

    @Test
    fun `glucoseUnit seeds from the cache and propagates flow emissions`() = runTest {
        val unitFlow = MutableStateFlow(GlucoseUnit.MGDL)
        every { appSettingsStore.glucoseUnit } returns GlucoseUnit.MGDL
        every { appSettingsStore.glucoseUnitFlow() } returns unitFlow
        val vm = createViewModel()

        val job = backgroundScope.launch(testDispatcher) { vm.glucoseUnit.collect { } }
        advanceUntilIdle()
        assertEquals(GlucoseUnit.MGDL, vm.glucoseUnit.value)

        unitFlow.value = GlucoseUnit.MMOL
        advanceUntilIdle()
        assertEquals(GlucoseUnit.MMOL, vm.glucoseUnit.value)

        job.cancel()
    }

    @Test
    fun `refreshAlerts calls fetchPendingAlerts`() = runTest {
        val vm = createViewModel()
        advanceUntilIdle()

        vm.refreshAlerts()
        advanceUntilIdle()

        // Once from init, once from explicit call
        coVerify(atLeast = 2) { repository.fetchPendingAlerts() }
    }

    @Test
    fun `refreshAlerts sets user-facing error on failure, never the raw exception message`() = runTest {
        coEvery { repository.fetchPendingAlerts() } returns
            Result.failure(RuntimeException("java.net.SocketException: raw internals"))

        val vm = createViewModel()
        advanceUntilIdle()

        assertEquals("Couldn't refresh alerts. Try again.", vm.uiState.value.error)
        assertFalse(vm.uiState.value.isLoading)
    }

    @Test
    fun `refreshAlerts offline failure reaches a terminal state with connection copy`() = runTest {
        coEvery { repository.fetchPendingAlerts() } returns
            Result.failure(java.io.IOException("connect timed out"))

        val vm = createViewModel()
        advanceUntilIdle()

        // Terminal: not loading, honest copy, no raw exception text.
        assertFalse(vm.uiState.value.isLoading)
        assertEquals("Can't reach your server — alerts may be out of date.", vm.uiState.value.error)
    }

    @Test
    fun `acknowledgeAlert calls repository`() = runTest {
        coEvery { repository.acknowledgeAlert("alert-1") } returns Result.success(Unit)

        val vm = createViewModel()
        advanceUntilIdle()

        vm.acknowledgeAlert("alert-1")
        advanceUntilIdle()

        coVerify { repository.acknowledgeAlert("alert-1") }
    }

    @Test
    fun `acknowledgeAlert calls markAcknowledged on success`() = runTest {
        coEvery { repository.acknowledgeAlert("alert-1") } returns Result.success(Unit)

        val vm = createViewModel()
        advanceUntilIdle()

        vm.acknowledgeAlert("alert-1")
        advanceUntilIdle()

        verify { notificationManager.markAcknowledged("alert-1") }
    }

    @Test
    fun `acknowledgeAlert does not call markAcknowledged on failure`() = runTest {
        coEvery { repository.acknowledgeAlert("alert-1") } returns
            Result.failure(RuntimeException("Forbidden"))

        val vm = createViewModel()
        advanceUntilIdle()

        vm.acknowledgeAlert("alert-1")
        advanceUntilIdle()

        verify(exactly = 0) { notificationManager.markAcknowledged(any()) }
    }

    @Test
    fun `acknowledgeAlert sets user-facing error on failure, never the raw exception message`() = runTest {
        coEvery { repository.acknowledgeAlert("alert-1") } returns
            Result.failure(RuntimeException("Acknowledge failed: HTTP 403"))

        val vm = createViewModel()
        advanceUntilIdle()

        vm.acknowledgeAlert("alert-1")
        advanceUntilIdle()

        assertEquals("Couldn't acknowledge the alert. Try again.", vm.uiState.value.error)
    }

    @Test
    fun `clearError resets error state`() = runTest {
        coEvery { repository.fetchPendingAlerts() } returns
            Result.failure(RuntimeException("fail"))

        val vm = createViewModel()
        advanceUntilIdle()

        assertEquals("Couldn't refresh alerts. Try again.", vm.uiState.value.error)

        vm.clearError()
        assertNull(vm.uiState.value.error)
    }

    // -- alertingDegraded (AC4 banner input) -----------------------------------

    @Test
    fun `alerting is not degraded when backend reachable and stream connected`() = runTest {
        alertStreamStateHolder.onStreamOpened()
        val vm = createViewModel()

        val job = backgroundScope.launch(testDispatcher) { vm.alertingDegraded.collect { } }
        advanceUntilIdle()

        assertFalse(vm.alertingDegraded.value)
        job.cancel()
    }

    @Test
    fun `alerting degrades when the backend becomes unreachable`() = runTest {
        alertStreamStateHolder.onStreamOpened()
        val vm = createViewModel()

        val job = backgroundScope.launch(testDispatcher) { vm.alertingDegraded.collect { } }
        advanceUntilIdle()
        assertFalse(vm.alertingDegraded.value)

        networkStatusFlow.value = NetworkStatus.BACKEND_UNREACHABLE
        advanceUntilIdle()

        assertTrue(vm.alertingDegraded.value)
        job.cancel()
    }

    @Test
    fun `alerting degrades when the stream drops and recovers on reconnect`() = runTest {
        alertStreamStateHolder.onStreamOpened()
        val vm = createViewModel()

        val job = backgroundScope.launch(testDispatcher) { vm.alertingDegraded.collect { } }
        advanceUntilIdle()
        assertFalse(vm.alertingDegraded.value)

        alertStreamStateHolder.onStreamRetrying()
        advanceUntilIdle()
        assertTrue(vm.alertingDegraded.value)

        alertStreamStateHolder.onStreamOpened()
        advanceUntilIdle()
        assertFalse(vm.alertingDegraded.value)

        job.cancel()
    }

    @Test
    fun `cached alerts still display while alerting is degraded`() = runTest {
        networkStatusFlow.value = NetworkStatus.BACKEND_UNREACHABLE
        coEvery { repository.fetchPendingAlerts() } returns
            Result.failure(java.io.IOException("unreachable"))
        alertsFlow.value = listOf(makeAlert())

        val vm = createViewModel()
        val degradedJob = backgroundScope.launch(testDispatcher) { vm.alertingDegraded.collect { } }
        val alertsJob = backgroundScope.launch(testDispatcher) { vm.alerts.collect { } }
        advanceUntilIdle()

        assertTrue(vm.alertingDegraded.value)
        assertEquals(1, vm.alerts.value.size)
        assertFalse(vm.uiState.value.isLoading)

        degradedJob.cancel()
        alertsJob.cancel()
    }
}
