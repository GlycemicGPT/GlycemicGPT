package com.glycemicgpt.mobile.presentation.meal

import android.content.Context
import android.net.Uri
import com.glycemicgpt.mobile.data.meal.CarbConfidence
import com.glycemicgpt.mobile.data.meal.CarbRange
import com.glycemicgpt.mobile.data.meal.CommonFood
import com.glycemicgpt.mobile.data.meal.FoodRecord
import com.glycemicgpt.mobile.data.meal.FoodRecordSource
import com.glycemicgpt.mobile.data.meal.ImageCompressor
import com.glycemicgpt.mobile.data.meal.MealException
import com.glycemicgpt.mobile.data.meal.MealPhotoFiles
import com.glycemicgpt.mobile.data.repository.MealRepository
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.justRun
import io.mockk.mockk
import io.mockk.mockkObject
import io.mockk.unmockkObject
import io.mockk.verify
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
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.IOException

@OptIn(ExperimentalCoroutinesApi::class)
class MealLogViewModelTest {

    private val testDispatcher = StandardTestDispatcher()
    private val repository = mockk<MealRepository>()
    private val context = mockk<Context>(relaxed = true)
    private val uri = mockk<Uri>(relaxed = true)

    private val record = FoodRecord(
        id = "rec-1",
        mealTimestamp = null,
        foodDescription = "pasta",
        estimate = CarbRange(40.0, 55.0),
        confidence = CarbConfidence.HIGH,
        source = FoodRecordSource.AI_ESTIMATE,
        correction = null,
        correctedAt = null,
        commonFoodId = null,
        createdAt = null,
    )

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
        mockkObject(ImageCompressor)
        mockkObject(MealPhotoFiles)
        justRun { MealPhotoFiles.clearCaptures(any()) }
        justRun { MealPhotoFiles.deleteCapture(any(), any()) }
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
        unmockkObject(ImageCompressor)
        unmockkObject(MealPhotoFiles)
    }

    private fun viewModel(): MealLogViewModel =
        MealLogViewModel(repository, context, testDispatcher)

    private fun stubAvailable() {
        coEvery { repository.probeAvailability() } returns Result.success(Unit)
    }

    @Test
    fun `availability check resolves to Ready`() = runTest(testDispatcher) {
        stubAvailable()
        val vm = viewModel()
        advanceUntilIdle()
        assertEquals(MealLogPageState.Ready, vm.uiState.value.pageState)
    }

    @Test
    fun `feature-off resolves to Disabled`() = runTest(testDispatcher) {
        coEvery { repository.probeAvailability() } returns
            Result.failure(MealException.FeatureDisabled())
        val vm = viewModel()
        advanceUntilIdle()
        assertEquals(MealLogPageState.Disabled, vm.uiState.value.pageState)
    }

    @Test
    fun `network failure resolves to Offline`() = runTest(testDispatcher) {
        coEvery { repository.probeAvailability() } returns
            Result.failure(IOException("down"))
        val vm = viewModel()
        advanceUntilIdle()
        assertEquals(MealLogPageState.Offline, vm.uiState.value.pageState)
    }

    @Test
    fun `successful upload surfaces the estimate`() = runTest(testDispatcher) {
        stubAvailable()
        every { ImageCompressor.compress(any(), any(), any(), any()) } returns ByteArray(8)
        coEvery { repository.uploadPhoto(any()) } returns Result.success(record)
        val vm = viewModel()
        advanceUntilIdle()

        vm.onImagePicked(uri)
        advanceUntilIdle()

        assertEquals(record, vm.uiState.value.record)
        assertEquals(uri, vm.uiState.value.photoUri)
        assertFalse(vm.uiState.value.isUploading)
        coVerify { repository.uploadPhoto(any()) }
    }

    @Test
    fun `a single upload keeps its photo for the result thumbnail`() = runTest(testDispatcher) {
        stubAvailable()
        every { ImageCompressor.compress(any(), any(), any(), any()) } returns ByteArray(8)
        coEvery { repository.uploadPhoto(any()) } returns Result.success(record)
        val vm = viewModel()
        advanceUntilIdle()

        vm.onImagePicked(uri)
        advanceUntilIdle()

        // The current capture must NOT be swept (the result needs it); cleanup is deferred to reset.
        verify(exactly = 0) { MealPhotoFiles.deleteCapture(any(), uri) }
    }

    @Test
    fun `a second pick sweeps the previous photo but keeps the new one`() = runTest(testDispatcher) {
        stubAvailable()
        every { ImageCompressor.compress(any(), any(), any(), any()) } returns ByteArray(8)
        coEvery { repository.uploadPhoto(any()) } returns Result.success(record)
        val secondUri = mockk<Uri>(relaxed = true)
        val vm = viewModel()
        advanceUntilIdle()

        vm.onImagePicked(uri)
        advanceUntilIdle()
        vm.onImagePicked(secondUri)
        advanceUntilIdle()

        verify { MealPhotoFiles.deleteCapture(any(), uri) }
        verify(exactly = 0) { MealPhotoFiles.deleteCapture(any(), secondUri) }
    }

    @Test
    fun `vision-unavailable upload sets the dedicated state`() = runTest(testDispatcher) {
        stubAvailable()
        every { ImageCompressor.compress(any(), any(), any(), any()) } returns ByteArray(8)
        coEvery { repository.uploadPhoto(any()) } returns
            Result.failure(MealException.VisionUnavailable())
        val vm = viewModel()
        advanceUntilIdle()

        vm.onImagePicked(uri)
        advanceUntilIdle()

        assertEquals(MealUnavailableReason.VISION, vm.uiState.value.unavailableReason)
        assertNull(vm.uiState.value.record)
    }

    @Test
    fun `no-provider upload sets the no-provider state`() = runTest(testDispatcher) {
        stubAvailable()
        every { ImageCompressor.compress(any(), any(), any(), any()) } returns ByteArray(8)
        coEvery { repository.uploadPhoto(any()) } returns
            Result.failure(MealException.NoAiProvider())
        val vm = viewModel()
        advanceUntilIdle()

        vm.onImagePicked(uri)
        advanceUntilIdle()

        assertEquals(MealUnavailableReason.NO_PROVIDER, vm.uiState.value.unavailableReason)
        assertNull(vm.uiState.value.record)
    }

    @Test
    fun `feature-off discovered during upload flips the page to Disabled`() = runTest(testDispatcher) {
        stubAvailable()
        every { ImageCompressor.compress(any(), any(), any(), any()) } returns ByteArray(8)
        coEvery { repository.uploadPhoto(any()) } returns
            Result.failure(MealException.FeatureDisabled())
        val vm = viewModel()
        advanceUntilIdle()

        vm.onImagePicked(uri)
        advanceUntilIdle()

        assertEquals(MealLogPageState.Disabled, vm.uiState.value.pageState)
    }

    @Test
    fun `unreadable photo shows a friendly error`() = runTest(testDispatcher) {
        stubAvailable()
        every { ImageCompressor.compress(any(), any(), any(), any()) } throws IOException("bad")
        val vm = viewModel()
        advanceUntilIdle()

        vm.onImagePicked(uri)
        advanceUntilIdle()

        assertFalse(vm.uiState.value.isUploading)
        assertTrue(vm.uiState.value.errorMessage!!.contains("Couldn't read"))
    }

    @Test
    fun `a non-IO compression failure recovers instead of leaving the spinner stuck`() =
        runTest(testDispatcher) {
            stubAvailable()
            // BitmapFactory / createScaledBitmap can throw unchecked exceptions on a bad image.
            every { ImageCompressor.compress(any(), any(), any(), any()) } throws
                IllegalArgumentException("bad bitmap dimensions")
            val vm = viewModel()
            advanceUntilIdle()

            vm.onImagePicked(uri)
            advanceUntilIdle()

            assertFalse(vm.uiState.value.isUploading)
            assertTrue(vm.uiState.value.errorMessage!!.contains("Couldn't read"))
        }

    @Test
    fun `out-of-memory during compression recovers with a smaller-photo hint`() =
        runTest(testDispatcher) {
            stubAvailable()
            every { ImageCompressor.compress(any(), any(), any(), any()) } throws OutOfMemoryError()
            val vm = viewModel()
            advanceUntilIdle()

            vm.onImagePicked(uri)
            advanceUntilIdle()

            assertFalse(vm.uiState.value.isUploading)
            assertTrue(vm.uiState.value.errorMessage!!.contains("too large"))
        }

    @Test
    fun `correction rejects an inverted range without calling the API`() = runTest(testDispatcher) {
        stubAvailable()
        every { ImageCompressor.compress(any(), any(), any(), any()) } returns ByteArray(8)
        coEvery { repository.uploadPhoto(any()) } returns Result.success(record)
        val vm = viewModel()
        advanceUntilIdle()
        vm.onImagePicked(uri)
        advanceUntilIdle()

        vm.submitCorrection("60", "40")
        advanceUntilIdle()

        assertTrue(vm.uiState.value.correctionError!!.contains("must not exceed"))
        coVerify(exactly = 0) { repository.correctRecord(any(), any(), any()) }
    }

    @Test
    fun `valid correction updates the record`() = runTest(testDispatcher) {
        stubAvailable()
        every { ImageCompressor.compress(any(), any(), any(), any()) } returns ByteArray(8)
        coEvery { repository.uploadPhoto(any()) } returns Result.success(record)
        val corrected = record.copy(
            source = FoodRecordSource.USER_CORRECTED,
            correction = CarbRange(45.0, 60.0),
        )
        coEvery { repository.correctRecord("rec-1", 45.0, 60.0) } returns Result.success(corrected)
        val vm = viewModel()
        advanceUntilIdle()
        vm.onImagePicked(uri)
        advanceUntilIdle()

        vm.submitCorrection("45", "60")
        advanceUntilIdle()

        assertEquals(corrected, vm.uiState.value.record)
        assertFalse(vm.uiState.value.isCorrecting)
    }

    @Test
    fun `save as common food requires a name`() = runTest(testDispatcher) {
        stubAvailable()
        every { ImageCompressor.compress(any(), any(), any(), any()) } returns ByteArray(8)
        coEvery { repository.uploadPhoto(any()) } returns Result.success(record)
        val vm = viewModel()
        advanceUntilIdle()
        vm.onImagePicked(uri)
        advanceUntilIdle()

        vm.saveAsCommonFood("   ")
        advanceUntilIdle()

        assertTrue(vm.uiState.value.errorMessage!!.contains("name"))
        coVerify(exactly = 0) { repository.saveAsCommonFood(any(), any()) }
    }

    @Test
    fun `save as common food confirms with the saved name`() = runTest(testDispatcher) {
        stubAvailable()
        every { ImageCompressor.compress(any(), any(), any(), any()) } returns ByteArray(8)
        coEvery { repository.uploadPhoto(any()) } returns Result.success(record)
        coEvery { repository.saveAsCommonFood("rec-1", "pasta") } returns Result.success(
            CommonFood(
                id = "cf-1",
                name = "pasta",
                carbs = CarbRange(40.0, 55.0),
                createdAt = null,
                updatedAt = null,
            ),
        )
        val vm = viewModel()
        advanceUntilIdle()
        vm.onImagePicked(uri)
        advanceUntilIdle()

        vm.saveAsCommonFood("pasta")
        advanceUntilIdle()

        assertEquals("pasta", vm.uiState.value.savedCommonFoodName)
    }
}
