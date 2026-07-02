package com.glycemicgpt.mobile.presentation.meal

import com.glycemicgpt.mobile.data.meal.CarbConfidence
import com.glycemicgpt.mobile.data.meal.CarbRange
import com.glycemicgpt.mobile.data.meal.FoodRecord
import com.glycemicgpt.mobile.data.meal.FoodRecordSource
import com.glycemicgpt.mobile.data.meal.MealException
import com.glycemicgpt.mobile.data.repository.MealRepository
import io.mockk.coEvery
import io.mockk.mockk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class MealHistoryViewModelTest {

    private val testDispatcher = StandardTestDispatcher()
    private val repository = mockk<MealRepository>()

    private fun record(id: String) = FoodRecord(
        id = id,
        mealTimestamp = null,
        foodDescription = "meal $id",
        estimate = CarbRange(40.0, 55.0),
        confidence = CarbConfidence.MEDIUM,
        source = FoodRecordSource.AI_ESTIMATE,
        correction = null,
        correctedAt = null,
        commonFoodId = null,
        createdAt = null,
    )

    @Before fun setUp() = Dispatchers.setMain(testDispatcher)

    @After fun tearDown() = Dispatchers.resetMain()

    @Test
    fun `loads records on init`() = runTest(testDispatcher) {
        coEvery { repository.listFoodRecords(any(), any()) } returns
            Result.success(listOf(record("a"), record("b")))
        val vm = MealHistoryViewModel(repository)
        advanceUntilIdle()

        assertFalse(vm.uiState.value.isLoading)
        assertEquals(2, vm.uiState.value.records.size)
    }

    @Test
    fun `feature-off marks the screen disabled`() = runTest(testDispatcher) {
        coEvery { repository.listFoodRecords(any(), any()) } returns
            Result.failure(MealException.FeatureDisabled())
        val vm = MealHistoryViewModel(repository)
        advanceUntilIdle()

        assertTrue(vm.uiState.value.disabled)
    }

    @Test
    fun `offline load failure reaches a terminal state with honest copy`() = runTest(testDispatcher) {
        coEvery { repository.listFoodRecords(any(), any()) } returns
            Result.failure(java.io.IOException("failed to connect to /192.168.1.10:8000"))
        val vm = MealHistoryViewModel(repository)
        advanceUntilIdle()

        // Terminal: not loading, honest offline copy, never the raw exception message.
        assertFalse(vm.uiState.value.isLoading)
        assertEquals(
            "Can't reach your server — your meal history isn't available right now.",
            vm.uiState.value.errorMessage,
        )
    }

    @Test
    fun `unexpected load failure never surfaces the raw exception message`() = runTest(testDispatcher) {
        coEvery { repository.listFoodRecords(any(), any()) } returns
            Result.failure(IllegalStateException("moshi: expected BEGIN_OBJECT at path $.data"))
        val vm = MealHistoryViewModel(repository)
        advanceUntilIdle()

        assertFalse(vm.uiState.value.isLoading)
        assertEquals("Couldn't load your meal history.", vm.uiState.value.errorMessage)
    }

    @Test
    fun `retry after reconnect clears the error and loads records`() = runTest(testDispatcher) {
        coEvery { repository.listFoodRecords(any(), any()) } returns
            Result.failure(java.io.IOException("unreachable"))
        val vm = MealHistoryViewModel(repository)
        advanceUntilIdle()
        assertTrue(vm.uiState.value.errorMessage != null)

        coEvery { repository.listFoodRecords(any(), any()) } returns
            Result.success(listOf(record("a")))
        vm.load()
        advanceUntilIdle()

        assertEquals(null, vm.uiState.value.errorMessage)
        assertEquals(1, vm.uiState.value.records.size)
    }

    @Test
    fun `delete removes the record from the list`() = runTest(testDispatcher) {
        coEvery { repository.listFoodRecords(any(), any()) } returns
            Result.success(listOf(record("a"), record("b")))
        coEvery { repository.deleteFoodRecord("a") } returns Result.success(Unit)
        val vm = MealHistoryViewModel(repository)
        advanceUntilIdle()

        vm.delete("a")
        advanceUntilIdle()

        assertEquals(listOf("b"), vm.uiState.value.records.map { it.id })
    }
}
