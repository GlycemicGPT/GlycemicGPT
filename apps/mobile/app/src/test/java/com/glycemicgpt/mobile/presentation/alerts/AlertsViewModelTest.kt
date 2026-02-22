package com.glycemicgpt.mobile.presentation.alerts

import com.glycemicgpt.mobile.data.local.entity.AlertEntity
import com.glycemicgpt.mobile.data.repository.AlertRepository
import com.glycemicgpt.mobile.service.AlertNotificationManager
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
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
    private lateinit var repository: AlertRepository
    private lateinit var notificationManager: AlertNotificationManager

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
        repository = mockk(relaxed = true) {
            every { observeRecentAlerts() } returns alertsFlow
            coEvery { fetchPendingAlerts() } returns Result.success(emptyList())
        }
        notificationManager = mockk(relaxed = true)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun createViewModel() = AlertsViewModel(repository, notificationManager)

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
    fun `refreshAlerts calls fetchPendingAlerts`() = runTest {
        val vm = createViewModel()
        advanceUntilIdle()

        vm.refreshAlerts()
        advanceUntilIdle()

        // Once from init, once from explicit call
        coVerify(atLeast = 2) { repository.fetchPendingAlerts() }
    }

    @Test
    fun `refreshAlerts sets error on failure`() = runTest {
        coEvery { repository.fetchPendingAlerts() } returns
            Result.failure(RuntimeException("Network error"))

        val vm = createViewModel()
        advanceUntilIdle()

        assertEquals("Network error", vm.uiState.value.error)
        assertFalse(vm.uiState.value.isLoading)
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
    fun `acknowledgeAlert sets error on failure`() = runTest {
        coEvery { repository.acknowledgeAlert("alert-1") } returns
            Result.failure(RuntimeException("Forbidden"))

        val vm = createViewModel()
        advanceUntilIdle()

        vm.acknowledgeAlert("alert-1")
        advanceUntilIdle()

        assertEquals("Forbidden", vm.uiState.value.error)
    }

    @Test
    fun `clearError resets error state`() = runTest {
        coEvery { repository.fetchPendingAlerts() } returns
            Result.failure(RuntimeException("fail"))

        val vm = createViewModel()
        advanceUntilIdle()

        assertEquals("fail", vm.uiState.value.error)

        vm.clearError()
        assertNull(vm.uiState.value.error)
    }
}
