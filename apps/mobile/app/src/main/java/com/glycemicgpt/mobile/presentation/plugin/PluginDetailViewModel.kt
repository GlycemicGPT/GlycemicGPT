package com.glycemicgpt.mobile.presentation.plugin

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.glycemicgpt.mobile.domain.plugin.Plugin
import com.glycemicgpt.mobile.domain.plugin.PluginSettingsStore
import com.glycemicgpt.mobile.domain.plugin.ui.DetailScreenDescriptor
import com.glycemicgpt.mobile.plugin.PluginRegistry
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.conflate
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.launch
import timber.log.Timber
import javax.inject.Inject

@HiltViewModel
class PluginDetailViewModel @Inject constructor(
    private val pluginRegistry: PluginRegistry,
) : ViewModel() {

    private var plugin: Plugin? = null
    private var cardId: String? = null
    private var collectionJob: Job? = null

    private val _detailScreen = MutableStateFlow<DetailScreenDescriptor?>(null)
    val detailScreen: StateFlow<DetailScreenDescriptor?> = _detailScreen.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    private val _settingsStore = MutableStateFlow<PluginSettingsStore?>(null)
    val settingsStore: StateFlow<PluginSettingsStore?> = _settingsStore.asStateFlow()

    fun load(pluginId: String, cardId: String) {
        // Allow reload if args changed (e.g. navigation to a different card)
        if (this.plugin != null && this.cardId == cardId) return

        // Reset state for fresh load
        _error.value = null
        _detailScreen.value = null
        collectionJob?.cancel()

        val p = pluginRegistry.getPlugin(pluginId)
        if (p == null) {
            Timber.w("PluginDetailViewModel: plugin %s not found", pluginId)
            _error.value = "Plugin not found"
            return
        }

        this.plugin = p
        this.cardId = cardId
        _settingsStore.value = pluginRegistry.getPluginSettingsStore(pluginId)

        val flow = p.observeDetailScreen(cardId)
        if (flow == null) {
            Timber.w("PluginDetailViewModel: plugin %s has no detail for card %s", pluginId, cardId)
            _error.value = "No detail available for this card"
            return
        }

        collectionJob = viewModelScope.launch {
            try {
                flow
                    .flowOn(Dispatchers.IO)
                    .conflate()
                    .collect { descriptor ->
                        _error.value = null
                        _detailScreen.value = descriptor
                    }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Timber.e(e, "Plugin detail flow failed: pluginId=%s, cardId=%s", pluginId, cardId)
                _error.value = "Plugin encountered an error loading detail content"
            }
        }
    }

    fun onAction(key: String) {
        val cid = cardId ?: return
        viewModelScope.launch(Dispatchers.IO) {
            try {
                plugin?.onDetailAction(cid, key)
            } catch (e: Exception) {
                Timber.e(e, "Plugin detail action failed: cardId=%s, key=%s", cid, key)
                _error.value = "Action could not be completed"
            }
        }
    }
}
