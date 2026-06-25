package com.glycemicgpt.mobile.presentation.home

import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.local.AppSettingsStore.Companion.UNSET_FAB_OFFSET
import com.glycemicgpt.mobile.data.meal.CarbConfidence
import com.glycemicgpt.mobile.data.meal.CarbRange
import com.glycemicgpt.mobile.data.meal.FoodRecord
import com.glycemicgpt.mobile.data.meal.FoodRecordSource
import com.glycemicgpt.mobile.data.meal.MealException
import com.glycemicgpt.mobile.data.repository.MealRepository
import com.glycemicgpt.mobile.presentation.meal.FabOffset
import io.mockk.Runs
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.just
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
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
import java.io.IOException

@OptIn(ExperimentalCoroutinesApi::class)
class HomeMealViewModelTest {

    private val testDispatcher = StandardTestDispatcher()
    private val repository = mockk<MealRepository>()
    private val appSettingsStore = mockk<AppSettingsStore>()

    private fun record() = FoodRecord(
        id = "rec-1",
        mealTimestamp = null,
        foodDescription = "rice bowl",
        estimate = CarbRange(40.0, 50.0),
        confidence = CarbConfidence.MEDIUM,
        source = FoodRecordSource.AI_ESTIMATE,
        correction = null,
        correctedAt = null,
        commonFoodId = null,
        createdAt = null,
    )

    @Before fun setUp() {
        Dispatchers.setMain(testDispatcher)
        // Default: the per-account meal-intelligence setting is ON, so the FAB
        // gating defers to the server probe (the behavior these tests assert).
        every { appSettingsStore.mealIntelligenceEnabledFlow() } returns flowOf(true)
        every { appSettingsStore.mealIntelligenceEnabled } returns true
    }

    @After fun tearDown() = Dispatchers.resetMain()

    @Test
    fun `surfaces the most recent meal and keeps logging available`() = runTest(testDispatcher) {
        coEvery { repository.listFoodRecords(any(), any()) } returns Result.success(listOf(record()))
        val vm = HomeMealViewModel(repository, appSettingsStore)
        advanceUntilIdle()

        assertEquals("rec-1", vm.uiState.value.recentMeal?.id)
        assertTrue(vm.uiState.value.mealLoggingAvailable)
    }

    @Test
    fun `no meals yet keeps the FAB but hides the card`() = runTest(testDispatcher) {
        coEvery { repository.listFoodRecords(any(), any()) } returns Result.success(emptyList())
        val vm = HomeMealViewModel(repository, appSettingsStore)
        advanceUntilIdle()

        assertNull(vm.uiState.value.recentMeal)
        assertTrue(vm.uiState.value.mealLoggingAvailable)
    }

    @Test
    fun `local setting off hides the FAB without a server probe`() = runTest(testDispatcher) {
        every { appSettingsStore.mealIntelligenceEnabledFlow() } returns flowOf(false)
        every { appSettingsStore.mealIntelligenceEnabled } returns false
        val vm = HomeMealViewModel(repository, appSettingsStore)
        advanceUntilIdle()

        assertNull(vm.uiState.value.recentMeal)
        assertFalse(vm.uiState.value.mealLoggingAvailable)
        // The local gate short-circuits -- no network round-trip when off.
        coVerify(exactly = 0) { repository.listFoodRecords(any(), any()) }
    }

    @Test
    fun `toggling off cancels an in-flight probe so it cannot re-expose the FAB`() =
        runTest(testDispatcher) {
            // ON emit launches the probe; the following OFF emit must cancel it so a
            // late success can't flip mealLoggingAvailable back to true.
            every { appSettingsStore.mealIntelligenceEnabled } returns true
            every { appSettingsStore.mealIntelligenceEnabledFlow() } returns flowOf(true, false)
            coEvery { repository.listFoodRecords(any(), any()) } returns
                Result.success(listOf(record()))
            val vm = HomeMealViewModel(repository, appSettingsStore)
            advanceUntilIdle()

            assertFalse(vm.uiState.value.mealLoggingAvailable)
            assertNull(vm.uiState.value.recentMeal)
        }

    @Test
    fun `feature-off hides the FAB`() = runTest(testDispatcher) {
        coEvery { repository.listFoodRecords(any(), any()) } returns
            Result.failure(MealException.FeatureDisabled())
        val vm = HomeMealViewModel(repository, appSettingsStore)
        advanceUntilIdle()

        assertNull(vm.uiState.value.recentMeal)
        assertFalse(vm.uiState.value.mealLoggingAvailable)
    }

    @Test
    fun `a transient failure keeps the FAB so the meal screen can degrade itself`() =
        runTest(testDispatcher) {
            coEvery { repository.listFoodRecords(any(), any()) } returns
                Result.failure(IOException("offline"))
            val vm = HomeMealViewModel(repository, appSettingsStore)
            advanceUntilIdle()

            assertNull(vm.uiState.value.recentMeal)
            assertTrue(vm.uiState.value.mealLoggingAvailable)
        }

    @Test
    fun `savedFabOffset is null when the user has never moved the FAB`() = runTest(testDispatcher) {
        coEvery { repository.listFoodRecords(any(), any()) } returns Result.success(emptyList())
        every { appSettingsStore.mealFabOffsetXPx } returns UNSET_FAB_OFFSET
        every { appSettingsStore.mealFabOffsetYPx } returns UNSET_FAB_OFFSET
        val vm = HomeMealViewModel(repository, appSettingsStore)
        advanceUntilIdle()

        assertNull(vm.savedFabOffset())
    }

    @Test
    fun `savedFabOffset returns the stored px position`() = runTest(testDispatcher) {
        coEvery { repository.listFoodRecords(any(), any()) } returns Result.success(emptyList())
        every { appSettingsStore.mealFabOffsetXPx } returns 120
        every { appSettingsStore.mealFabOffsetYPx } returns 340
        val vm = HomeMealViewModel(repository, appSettingsStore)
        advanceUntilIdle()

        val offset = vm.savedFabOffset()
        assertEquals(FabOffset(120f, 340f), offset)
    }

    @Test
    fun `savedFabOffset is null when only one axis is set`() = runTest(testDispatcher) {
        coEvery { repository.listFoodRecords(any(), any()) } returns Result.success(emptyList())
        every { appSettingsStore.mealFabOffsetXPx } returns 120
        every { appSettingsStore.mealFabOffsetYPx } returns UNSET_FAB_OFFSET
        val vm = HomeMealViewModel(repository, appSettingsStore)
        advanceUntilIdle()

        // Either axis unset means "never placed" -> default, never a half-resolved coordinate.
        assertNull(vm.savedFabOffset())
    }

    @Test
    fun `persistFabOffset writes the rounded px position in one atomic call`() =
        runTest(testDispatcher) {
            coEvery { repository.listFoodRecords(any(), any()) } returns Result.success(emptyList())
            every { appSettingsStore.setMealFabOffset(any(), any()) } just Runs
            val vm = HomeMealViewModel(repository, appSettingsStore)
            advanceUntilIdle()

            vm.persistFabOffset(FabOffset(120.4f, 340.6f))

            verify(exactly = 1) { appSettingsStore.setMealFabOffset(120, 341) }
        }
}
