package com.glycemicgpt.mobile.presentation.home

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
import javax.inject.Inject

/**
 * Drives the Home meal glance (the camera FAB + Recent-meal card) independently of the pump-data
 * [HomeViewModel] so the two domains stay separate. One cheap call surfaces the most recent meal and
 * tells us whether the feature is available.
 */
data class HomeMealUiState(
    /** Most recent logged meal; null hides the Recent-meal card. */
    val recentMeal: FoodRecord? = null,
    /**
     * Whether to offer meal logging (the FAB). False only when the server flag is known-off; on a
     * transient/offline failure we keep the FAB so the meal screen can show its own degraded state.
     */
    val mealLoggingAvailable: Boolean = true,
)

@HiltViewModel
class HomeMealViewModel @Inject constructor(
    private val repository: MealRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(HomeMealUiState())
    val uiState: StateFlow<HomeMealUiState> = _uiState.asStateFlow()

    init {
        refresh()
    }

    /** Re-fetch the most recent meal; safe to call on Home resume / pull-to-refresh. */
    fun refresh() {
        viewModelScope.launch {
            repository.listFoodRecords(limit = 1)
                .onSuccess { records ->
                    _uiState.update {
                        it.copy(recentMeal = records.firstOrNull(), mealLoggingAvailable = true)
                    }
                }
                .onFailure { e ->
                    _uiState.update {
                        it.copy(
                            recentMeal = null,
                            // Hide the FAB only when the server explicitly disabled the feature.
                            mealLoggingAvailable = e !is MealException.FeatureDisabled,
                        )
                    }
                }
        }
    }
}
