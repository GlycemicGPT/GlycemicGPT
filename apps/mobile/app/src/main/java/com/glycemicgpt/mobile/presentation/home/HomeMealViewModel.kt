package com.glycemicgpt.mobile.presentation.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.local.AppSettingsStore.Companion.UNSET_FAB_OFFSET
import com.glycemicgpt.mobile.data.meal.FoodRecord
import com.glycemicgpt.mobile.data.meal.MealException
import com.glycemicgpt.mobile.data.repository.MealRepository
import com.glycemicgpt.mobile.presentation.meal.FabOffset
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject
import kotlin.math.roundToInt

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
    private val appSettingsStore: AppSettingsStore,
) : ViewModel() {

    private val _uiState = MutableStateFlow(HomeMealUiState())
    val uiState: StateFlow<HomeMealUiState> = _uiState.asStateFlow()

    // The in-flight probe, cancelled when the setting flips off so a late response
    // can't re-expose the FAB after the user turned the feature off.
    private var refreshJob: Job? = null

    init {
        // The per-account setting (cached locally) gates the FAB instantly when the
        // user toggles it -- no network round-trip. When on, confirm against the
        // server probe (which also surfaces the most recent meal).
        viewModelScope.launch {
            appSettingsStore.mealIntelligenceEnabledFlow().collect { enabled ->
                if (enabled) {
                    refresh()
                } else {
                    refreshJob?.cancel()
                    _uiState.update {
                        it.copy(recentMeal = null, mealLoggingAvailable = false)
                    }
                }
            }
        }
    }

    /**
     * The user's saved FAB position (px), or null if they've never moved it (use the default
     * placement). Read once when Home first composes -- a per-device UI preference, not reactive.
     */
    fun savedFabOffset(): FabOffset? {
        val x = appSettingsStore.mealFabOffsetXPx
        val y = appSettingsStore.mealFabOffsetYPx
        return if (x == UNSET_FAB_OFFSET || y == UNSET_FAB_OFFSET) {
            null
        } else {
            FabOffset(x.toFloat(), y.toFloat())
        }
    }

    /** Persist the FAB position (px) once a drag settles, so it survives navigation and restarts. */
    fun persistFabOffset(offset: FabOffset) {
        appSettingsStore.setMealFabOffset(offset.x.roundToInt(), offset.y.roundToInt())
    }

    /** Forget the saved FAB position so it returns to the default placement (accessibility reset). */
    fun resetFabOffset() {
        appSettingsStore.clearMealFabOffset()
    }

    /** Re-fetch the most recent meal; safe to call on Home resume / pull-to-refresh. */
    fun refresh() {
        // The local setting gates the FAB without a round-trip; skip the probe when off.
        if (!appSettingsStore.mealIntelligenceEnabled) {
            refreshJob?.cancel()
            _uiState.update { it.copy(recentMeal = null, mealLoggingAvailable = false) }
            return
        }
        refreshJob?.cancel()
        refreshJob = viewModelScope.launch {
            repository.listFoodRecords(limit = 1)
                .onSuccess { records ->
                    // Re-check: the toggle may have flipped off while the probe was
                    // in flight, in which case the off-handler already hid the FAB.
                    if (!appSettingsStore.mealIntelligenceEnabled) return@onSuccess
                    _uiState.update {
                        it.copy(recentMeal = records.firstOrNull(), mealLoggingAvailable = true)
                    }
                }
                .onFailure { e ->
                    if (!appSettingsStore.mealIntelligenceEnabled) return@onFailure
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
