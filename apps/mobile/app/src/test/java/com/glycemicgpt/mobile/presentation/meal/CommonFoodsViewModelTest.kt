package com.glycemicgpt.mobile.presentation.meal

import com.glycemicgpt.mobile.data.meal.CarbRange
import com.glycemicgpt.mobile.data.meal.CommonFood
import com.glycemicgpt.mobile.data.meal.MealException
import com.glycemicgpt.mobile.data.repository.MealRepository
import io.mockk.coEvery
import io.mockk.coVerify
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
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class CommonFoodsViewModelTest {

    private val testDispatcher = StandardTestDispatcher()
    private val repository = mockk<MealRepository>()

    private fun food(id: String, name: String) = CommonFood(
        id = id,
        name = name,
        carbs = CarbRange(40.0, 55.0),
        createdAt = null,
        updatedAt = null,
    )

    @Before fun setUp() = Dispatchers.setMain(testDispatcher)

    @After fun tearDown() = Dispatchers.resetMain()

    @Test
    fun `loads common foods on init`() = runTest(testDispatcher) {
        coEvery { repository.listCommonFoods(any(), any()) } returns
            Result.success(listOf(food("a", "pasta")))
        val vm = CommonFoodsViewModel(repository)
        advanceUntilIdle()

        assertEquals(1, vm.uiState.value.items.size)
    }

    @Test
    fun `edit validates carbs before calling the API`() = runTest(testDispatcher) {
        coEvery { repository.listCommonFoods(any(), any()) } returns
            Result.success(listOf(food("a", "pasta")))
        val vm = CommonFoodsViewModel(repository)
        advanceUntilIdle()

        vm.startEdit(food("a", "pasta"))
        vm.saveEdit("pasta", "60", "40")
        advanceUntilIdle()

        assertTrue(vm.uiState.value.editError!!.contains("must not exceed"))
        coVerify(exactly = 0) { repository.updateCommonFood(any(), any(), any(), any()) }
    }

    @Test
    fun `successful edit updates the item and closes the dialog`() = runTest(testDispatcher) {
        coEvery { repository.listCommonFoods(any(), any()) } returns
            Result.success(listOf(food("a", "pasta")))
        coEvery { repository.updateCommonFood("a", "penne", 30.0, 45.0) } returns
            Result.success(food("a", "penne").copy(carbs = CarbRange(30.0, 45.0)))
        val vm = CommonFoodsViewModel(repository)
        advanceUntilIdle()

        vm.startEdit(food("a", "pasta"))
        vm.saveEdit("penne", "30", "45")
        advanceUntilIdle()

        assertNull(vm.uiState.value.editing)
        assertEquals("penne", vm.uiState.value.items.first().name)
    }

    @Test
    fun `name conflict surfaces a clear edit error`() = runTest(testDispatcher) {
        coEvery { repository.listCommonFoods(any(), any()) } returns
            Result.success(listOf(food("a", "pasta")))
        coEvery { repository.updateCommonFood(any(), any(), any(), any()) } returns
            Result.failure(MealException.NameConflict())
        val vm = CommonFoodsViewModel(repository)
        advanceUntilIdle()

        vm.startEdit(food("a", "pasta"))
        vm.saveEdit("rice", "40", "55")
        advanceUntilIdle()

        assertTrue(vm.uiState.value.editError!!.contains("already exists"))
    }

    @Test
    fun `delete removes the item`() = runTest(testDispatcher) {
        coEvery { repository.listCommonFoods(any(), any()) } returns
            Result.success(listOf(food("a", "pasta"), food("b", "rice")))
        coEvery { repository.deleteCommonFood("a") } returns Result.success(Unit)
        val vm = CommonFoodsViewModel(repository)
        advanceUntilIdle()

        vm.delete("a")
        advanceUntilIdle()

        assertEquals(listOf("b"), vm.uiState.value.items.map { it.id })
    }
}
