package com.glycemicgpt.mobile.presentation.meal

import android.content.Context
import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.glycemicgpt.mobile.data.meal.CarbBounds
import com.glycemicgpt.mobile.data.meal.CarbInputResult
import com.glycemicgpt.mobile.data.meal.FoodRecord
import com.glycemicgpt.mobile.data.meal.ImageCompressor
import com.glycemicgpt.mobile.data.meal.MealException
import com.glycemicgpt.mobile.data.meal.MealPhotoFiles
import com.glycemicgpt.mobile.data.repository.MealRepository
import com.glycemicgpt.mobile.di.IoDispatcher
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.io.IOException
import javax.inject.Inject

/** Availability of the meal feature, determined once when the screen opens. */
sealed interface MealLogPageState {
    data object Loading : MealLogPageState
    data object Ready : MealLogPageState

    /** The backend feature flag is off; the capture UI is hidden. */
    data object Disabled : MealLogPageState

    /** Could not reach the backend to determine availability; offer a retry. */
    data object Offline : MealLogPageState
}

/** Why an estimate can't be produced for this user's AI setup -- a dead-end, not a retryable error. */
enum class MealUnavailableReason {
    /** AC5: the user's AI provider has no vision route (backend 422 vision_unavailable). */
    VISION,

    /** The user has no AI provider configured at all (backend 404). */
    NO_PROVIDER,
}

data class MealLogUiState(
    val pageState: MealLogPageState = MealLogPageState.Loading,
    val isUploading: Boolean = false,
    val record: FoodRecord? = null,
    /** The just-picked/captured image, shown as a thumbnail on the result. Null when none. */
    val photoUri: Uri? = null,
    /** Set when the user's AI setup can't produce an estimate (vision-less or no provider). */
    val unavailableReason: MealUnavailableReason? = null,
    val errorMessage: String? = null,
    val isCorrecting: Boolean = false,
    val isSavingCorrection: Boolean = false,
    val correctionError: String? = null,
    val isSavingCommonFood: Boolean = false,
    val savedCommonFoodName: String? = null,
)

@HiltViewModel
class MealLogViewModel @Inject constructor(
    private val repository: MealRepository,
    @ApplicationContext private val context: Context,
    @IoDispatcher private val ioDispatcher: CoroutineDispatcher,
) : ViewModel() {

    private val _uiState = MutableStateFlow(MealLogUiState())
    val uiState: StateFlow<MealLogUiState> = _uiState.asStateFlow()

    /** The in-flight compress+upload job, cancelled when a new photo supersedes it. */
    private var uploadJob: Job? = null

    init {
        checkAvailability()
    }

    /** Probe the feature flag via a cheap call so feature-off degrades to [Disabled]. */
    fun checkAvailability() {
        _uiState.update { it.copy(pageState = MealLogPageState.Loading) }
        viewModelScope.launch {
            repository.probeAvailability()
                .onSuccess { _uiState.update { s -> s.copy(pageState = MealLogPageState.Ready) } }
                .onFailure { e ->
                    val next = when (e) {
                        is MealException.FeatureDisabled -> MealLogPageState.Disabled
                        else -> MealLogPageState.Offline
                    }
                    _uiState.update { s -> s.copy(pageState = next) }
                }
        }
    }

    /** Compress and upload a captured/picked image, then surface the estimate. */
    fun onImagePicked(uri: Uri) {
        // Cancel any in-flight compress/upload before superseding it, so the previous capture's
        // file can't be deleted out from under an active read.
        uploadJob?.cancel()
        val previousPhoto = _uiState.value.photoUri
        _uiState.update {
            it.copy(
                isUploading = true,
                errorMessage = null,
                unavailableReason = null,
                record = null,
                photoUri = uri,
                savedCommonFoodName = null,
                isCorrecting = false,
            )
        }
        uploadJob = viewModelScope.launch {
            // Drop the prior capture's original (scoped; no-op for gallery URIs). The current photo
            // is kept so the result can show a thumbnail, and is swept on reset().
            if (previousPhoto != null) {
                withContext(ioDispatcher) { MealPhotoFiles.deleteCapture(context, previousPhoto) }
            }
            val bytes = try {
                withContext(ioDispatcher) {
                    ImageCompressor.compress(context.contentResolver, uri)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: OutOfMemoryError) {
                // A very large source can exhaust heap during decode/scale; recover instead of
                // leaving the upload spinner stuck (or crashing).
                Timber.w(e, "Out of memory compressing meal photo")
                _uiState.update {
                    it.copy(
                        isUploading = false,
                        errorMessage = "That photo is too large to process. Try a smaller one.",
                    )
                }
                return@launch
            } catch (e: Exception) {
                // IOException plus the unchecked IllegalArgument/IllegalState that
                // BitmapFactory/createScaledBitmap can throw on a malformed image -- caught so the
                // spinner can never get permanently stuck.
                Timber.w(e, "Failed to read meal photo")
                _uiState.update {
                    it.copy(isUploading = false, errorMessage = "Couldn't read that photo. Try another one.")
                }
                return@launch
            }

            repository.uploadPhoto(bytes)
                .onSuccess { record ->
                    _uiState.update { it.copy(isUploading = false, record = record) }
                }
                .onFailure { e -> handleUploadFailure(e) }
        }
    }

    private fun handleUploadFailure(e: Throwable) {
        when (e) {
            is MealException.VisionUnavailable ->
                _uiState.update {
                    it.copy(isUploading = false, unavailableReason = MealUnavailableReason.VISION)
                }
            is MealException.NoAiProvider ->
                _uiState.update {
                    it.copy(isUploading = false, unavailableReason = MealUnavailableReason.NO_PROVIDER)
                }
            is MealException.FeatureDisabled ->
                _uiState.update {
                    it.copy(isUploading = false, pageState = MealLogPageState.Disabled)
                }
            else ->
                _uiState.update { it.copy(isUploading = false, errorMessage = messageFor(e)) }
        }
    }

    fun startCorrection() {
        // Drop any stale save-confirmation: it referred to the pre-correction baseline.
        _uiState.update { it.copy(isCorrecting = true, correctionError = null, savedCommonFoodName = null) }
    }

    fun cancelCorrection() {
        _uiState.update { it.copy(isCorrecting = false, correctionError = null) }
    }

    fun submitCorrection(lowText: String, highText: String) {
        val record = _uiState.value.record ?: return
        val parsed = when (val result = CarbBounds.parse(lowText, highText)) {
            is CarbInputResult.Invalid -> {
                _uiState.update { it.copy(correctionError = result.reason) }
                return
            }
            is CarbInputResult.Valid -> result
        }
        _uiState.update { it.copy(isSavingCorrection = true, correctionError = null) }
        viewModelScope.launch {
            repository.correctRecord(record.id, parsed.lowGrams, parsed.highGrams)
                .onSuccess { updated ->
                    _uiState.update {
                        it.copy(isSavingCorrection = false, isCorrecting = false, record = updated)
                    }
                }
                .onFailure { e ->
                    _uiState.update {
                        it.copy(isSavingCorrection = false, correctionError = messageFor(e))
                    }
                }
        }
    }

    fun saveAsCommonFood(name: String) {
        val record = _uiState.value.record ?: return
        val trimmed = name.trim()
        if (trimmed.isEmpty()) {
            _uiState.update { it.copy(errorMessage = "Give this food a name first.") }
            return
        }
        _uiState.update { it.copy(isSavingCommonFood = true, errorMessage = null) }
        viewModelScope.launch {
            repository.saveAsCommonFood(record.id, trimmed)
                .onSuccess { saved ->
                    _uiState.update {
                        it.copy(isSavingCommonFood = false, savedCommonFoodName = saved.name)
                    }
                }
                .onFailure { e ->
                    _uiState.update { it.copy(isSavingCommonFood = false, errorMessage = messageFor(e)) }
                }
        }
    }

    /** Return to the idle capture state to log another meal. */
    fun reset() {
        // No capture is in flight here, so sweep the kept result thumbnail + any orphaned originals.
        viewModelScope.launch { withContext(ioDispatcher) { MealPhotoFiles.clearCaptures(context) } }
        _uiState.update {
            it.copy(
                isUploading = false,
                record = null,
                photoUri = null,
                unavailableReason = null,
                errorMessage = null,
                isCorrecting = false,
                isSavingCorrection = false,
                correctionError = null,
                isSavingCommonFood = false,
                savedCommonFoodName = null,
            )
        }
    }

    fun clearError() {
        _uiState.update { it.copy(errorMessage = null) }
    }

    private fun messageFor(e: Throwable): String = when (e) {
        is MealException -> e.message ?: "Something went wrong. Please try again."
        is IOException -> "Check your connection and try again."
        else -> e.message ?: "Something went wrong. Please try again."
    }
}
