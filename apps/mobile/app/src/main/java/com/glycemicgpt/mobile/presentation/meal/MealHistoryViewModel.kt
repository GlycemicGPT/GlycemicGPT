package com.glycemicgpt.mobile.presentation.meal

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.glycemicgpt.mobile.data.meal.FoodRecord
import com.glycemicgpt.mobile.data.meal.MealException
import com.glycemicgpt.mobile.data.repository.MealRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.io.IOException
import javax.inject.Inject

data class MealHistoryUiState(
    val isLoading: Boolean = true,
    val records: List<FoodRecord> = emptyList(),
    val errorMessage: String? = null,
    /** Transient failure of a row action (e.g. delete), surfaced as a snackbar then cleared. */
    val actionError: String? = null,
    /** Backend feature flag is off; show a degraded message instead of an empty list. */
    val disabled: Boolean = false,
)

@HiltViewModel
class MealHistoryViewModel @Inject constructor(
    private val repository: MealRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(MealHistoryUiState())
    val uiState: StateFlow<MealHistoryUiState> = _uiState.asStateFlow()

    init {
        load()
    }

    fun load() {
        _uiState.update { it.copy(isLoading = true, errorMessage = null) }
        viewModelScope.launch {
            repository.listFoodRecords()
                .onSuccess { records ->
                    _uiState.update {
                        it.copy(isLoading = false, records = records, disabled = false)
                    }
                }
                .onFailure { e -> _uiState.update { it.copy(isLoading = false).withError(e) } }
        }
    }

    fun delete(recordId: String) {
        viewModelScope.launch {
            repository.deleteFoodRecord(recordId)
                .onSuccess {
                    _uiState.update { s -> s.copy(records = s.records.filterNot { it.id == recordId }) }
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
        is MealException -> e.message ?: "Couldn't delete that meal."
        else -> "Couldn't delete that meal."
    }

    private fun MealHistoryUiState.withError(e: Throwable): MealHistoryUiState = when (e) {
        is MealException.FeatureDisabled -> copy(disabled = true, errorMessage = null)
        is IOException -> copy(
            errorMessage = "Can't reach your server — your meal history isn't available right now.",
        )
        is MealException -> copy(errorMessage = e.message ?: "Couldn't load your meal history.")
        // Never surface a raw exception message for unexpected failures.
        else -> copy(errorMessage = "Couldn't load your meal history.")
    }
}
