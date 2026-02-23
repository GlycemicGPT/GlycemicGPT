package com.glycemicgpt.mobile.presentation.pairing

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.glycemicgpt.mobile.data.local.PumpCredentialStore
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.model.DiscoveredPump
import com.glycemicgpt.mobile.domain.pump.PumpConnectionManager
import com.glycemicgpt.mobile.domain.pump.PumpScanner
import com.glycemicgpt.mobile.service.PumpConnectionService
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class PairingViewModel @Inject constructor(
    private val pumpScanner: PumpScanner,
    private val connectionManager: PumpConnectionManager,
    private val credentialStore: PumpCredentialStore,
    @ApplicationContext private val appContext: Context,
) : ViewModel() {

    private val _discoveredPumps = MutableStateFlow<List<DiscoveredPump>>(emptyList())
    val discoveredPumps: StateFlow<List<DiscoveredPump>> = _discoveredPumps.asStateFlow()

    private val _isScanning = MutableStateFlow(false)
    val isScanning: StateFlow<Boolean> = _isScanning.asStateFlow()

    private val _pairingCode = MutableStateFlow("")
    val pairingCode: StateFlow<String> = _pairingCode.asStateFlow()

    private val _selectedPump = MutableStateFlow<DiscoveredPump?>(null)
    val selectedPump: StateFlow<DiscoveredPump?> = _selectedPump.asStateFlow()

    val connectionState: StateFlow<ConnectionState> = connectionManager.connectionState

    val isPaired: Boolean get() = credentialStore.isPaired()
    val pairedAddress: String? get() = credentialStore.getPairedAddress()

    private var scanJob: Job? = null

    fun startScan() {
        stopScan()
        _discoveredPumps.value = emptyList()
        _isScanning.value = true

        scanJob = viewModelScope.launch {
            try {
                pumpScanner.scan().collect { pump ->
                    _discoveredPumps.update { it + pump }
                }
            } finally {
                _isScanning.value = false
            }
        }
    }

    fun stopScan() {
        scanJob?.cancel()
        scanJob = null
        _isScanning.value = false
    }

    fun selectPump(pump: DiscoveredPump) {
        _selectedPump.value = pump
        stopScan()
    }

    fun clearSelection() {
        _selectedPump.value = null
        _pairingCode.value = ""
    }

    fun updatePairingCode(code: String) {
        // Allow up to 16 chars for legacy, 6 digits for modern
        _pairingCode.value = code.take(16)
    }

    fun pair() {
        val pump = _selectedPump.value ?: return
        val code = _pairingCode.value
        if (code.isEmpty()) return

        // Start the foreground service so polling begins once connected
        PumpConnectionService.start(appContext)
        connectionManager.connect(pump.address, code)
    }

    fun unpair() {
        connectionManager.unpair()
        PumpConnectionService.stop(appContext)
        _selectedPump.value = null
        _pairingCode.value = ""
    }

    override fun onCleared() {
        super.onCleared()
        stopScan()
    }
}
