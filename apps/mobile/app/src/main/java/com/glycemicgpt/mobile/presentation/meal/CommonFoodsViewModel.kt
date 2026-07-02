package com.glycemicgpt.mobile.presentation.meal

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.glycemicgpt.mobile.data.meal.CarbBounds
import com.glycemicgpt.mobile.data.meal.CarbInputResult
import com.glycemicgpt.mobile.data.meal.CommonFood
import com.glycemicgpt.mobile.data.meal.MealException
import com.glycemicgpt.mobile.data.repository.MealRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.io.IOException
import javax.inject.Inject

data class CommonFoodsUiState(
    val isLoading: Boolean = true,
    val items: List<CommonFood> = emptyList(),
    val errorMessage: String? = null,
    /** Transient failure of a row action (e.g. delete), surfaced as a snackbar then cleared. */
    val actionError: String? = null,
    val disabled: Boolean = false,
    /** The food currently open in the edit dialog, if any. */
    val editing: CommonFood? = null,
    val editError: String? = null,
    val isSaving: Boolean = false,
)

@HiltViewModel
class CommonFoodsViewModel @Inject constructor(
    private val repository: MealRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(CommonFoodsUiState())
    val uiState: StateFlow<CommonFoodsUiState> = _uiState.asStateFlow()

    private var loadJob: Job? = null

    init {
        load()
    }

    fun load() {
        // Cancel any in-flight load so a slow failing request can't resolve after a newer one
        // succeeded and clobber the screen with a stale full-screen error.
        loadJob?.cancel()
        // Reset disabled too: after a prior FeatureDisabled response, an offline retry must show
        // the honest offline state, not a stale "feature disabled" one. FeatureDisabled re-sets it.
        _uiState.update { it.copy(isLoading = true, errorMessage = null, disabled = false) }
        loadJob = viewModelScope.launch {
            val result = repository.listCommonFoods()
            // A repository that wraps errors in Result can swallow the CancellationException,
            // so a superseded load could still reach here — never let it write state.
            if (!isActive) return@launch
            result
                .onSuccess { items ->
                    _uiState.update { it.copy(isLoading = false, items = items, disabled = false) }
                }
                .onFailure { e -> _uiState.update { it.copy(isLoading = false).withError(e) } }
        }
    }

    fun startEdit(food: CommonFood) {
        _uiState.update { it.copy(editing = food, editError = null) }
    }

    fun cancelEdit() {
        _uiState.update { it.copy(editing = null, editError = null) }
    }

    fun saveEdit(name: String, lowText: String, highText: String) {
        val editing = _uiState.value.editing ?: return
        val trimmedName = name.trim()
        if (trimmedName.isEmpty()) {
            _uiState.update { it.copy(editError = "Name can't be empty.") }
            return
        }
        val parsed = when (val result = CarbBounds.parse(lowText, highText)) {
            is CarbInputResult.Invalid -> {
                _uiState.update { it.copy(editError = result.reason) }
                return
            }
            is CarbInputResult.Valid -> result
        }
        _uiState.update { it.copy(isSaving = true, editError = null) }
        viewModelScope.launch {
            repository.updateCommonFood(
                editing.id,
                name = trimmedName,
                carbsLow = parsed.lowGrams,
                carbsHigh = parsed.highGrams,
            )
                .onSuccess { updated ->
                    _uiState.update { s ->
                        s.copy(
                            isSaving = false,
                            editing = null,
                            items = s.items.map { if (it.id == updated.id) updated else it },
                        )
                    }
                }
                .onFailure { e ->
                    _uiState.update { it.copy(isSaving = false, editError = editMessageFor(e)) }
                }
        }
    }

    fun delete(commonFoodId: String) {
        viewModelScope.launch {
            repository.deleteCommonFood(commonFoodId)
                .onSuccess {
                    _uiState.update { s -> s.copy(items = s.items.filterNot { it.id == commonFoodId }) }
                }
                .onFailure { e ->
                    _uiState.update { it.copy(actionError = deleteMessageFor(e)) }
                }
        }
    }

    fun clearActionError() {
        _uiState.update { it.copy(actionError = null) }
    }

    private fun deleteMessageFor(e: Throwable): String = when (e) {
        is IOException -> "Check your connection and try again."
        is MealException -> e.message ?: "Couldn't delete that common food."
        else -> "Couldn't delete that common food."
    }

    private fun CommonFoodsUiState.withError(e: Throwable): CommonFoodsUiState = when (e) {
        is MealException.FeatureDisabled -> copy(disabled = true, errorMessage = null)
        is IOException -> copy(
            errorMessage = "Can't reach your server — your common foods aren't available right now.",
        )
        is MealException -> copy(errorMessage = e.message ?: "Couldn't load your common foods.")
        // Never surface a raw exception message for unexpected failures.
        else -> copy(errorMessage = "Couldn't load your common foods.")
    }

    private fun editMessageFor(e: Throwable): String = when (e) {
        is MealException.NameConflict -> e.message ?: "A common food with that name already exists."
        is MealException -> e.message ?: "Couldn't save your changes."
        is IOException -> "Check your connection and try again."
        // Never surface a raw exception message for unexpected failures.
        else -> "Couldn't save your changes."
    }
}
