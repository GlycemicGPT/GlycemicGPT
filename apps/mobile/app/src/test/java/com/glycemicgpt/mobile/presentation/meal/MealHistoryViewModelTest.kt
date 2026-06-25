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
