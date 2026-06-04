package com.glycemicgpt.mobile.presentation.pairing

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.glycemicgpt.mobile.data.local.PumpCredentialStore
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.model.DiscoveredPump
import com.glycemicgpt.mobile.domain.plugin.PairingFault
import com.glycemicgpt.mobile.domain.plugin.PairingProfile
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

    /** True while the phone is advertising and waiting for an advertise-and-wait pump to connect. */
    private val _isAdvertising = MutableStateFlow(false)
    val isAdvertising: StateFlow<Boolean> = _isAdvertising.asStateFlow()

    val connectionState: StateFlow<ConnectionState> = connectionManager.connectionState

    /** How the active pump pairs -- the screen renders the central-scan or advertise-and-wait flow off this. */
    val pairingProfile: StateFlow<PairingProfile> = connectionManager.pairingProfile

    /** Why an advertise-and-wait pairing is stalled/failed, or null. */
    val pairingFault: StateFlow<PairingFault?> = connectionManager.pairingFault

    val isPaired: Boolean get() = credentialStore.isPaired()
    val pairedAddress: String? get() = credentialStore.getPairedAddress()

    private var scanJob: Job? = null
    private var advertiseJob: Job? = null

    init {
        // Tie the polling/connection foreground service to an actual session, not to the user tapping
        // "Start Pairing". Starting it up front and then stopping it when advertising can't even begin
        // (e.g. a phone that can't act as a BLE peripheral, where scan() closes immediately) crashes the
        // app with ForegroundServiceDidNotStartInTime -- the service is torn down before it can promote
        // itself. Instead, start it only once a pump is actually connecting/connected, so polling is
        // ready and survives navigation away; it is stopped on unpair like the central-scan flow. Safe
        // and idempotent for Tandem, whose pair() already starts it at its own connection point.
        viewModelScope.launch {
            connectionState.collect { state ->
                if (state in SESSION_LIVE_OR_FORMING) {
                    PumpConnectionService.start(appContext)
                }
            }
        }
    }

    fun startScan() {
        stopScan()
        _discoveredPumps.value = emptyList()
        _isScanning.value = true

        scanJob = viewModelScope.launch {
            try {
                pumpScanner.scan().collect { pump ->
                    _discoveredPumps.update { current ->
                        val index = current.indexOfFirst { it.address == pump.address }
                        if (index == -1) current + pump else current.toMutableList().apply { set(index, pump) }
                    }
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

    /**
     * Advertise-and-wait pairing (phone-as-peripheral). Begins advertising and waits for the pump to
     * connect; the connection manager drives [connectionState] all the way to CONNECTED (SAKE has no
     * pairing code, so there is no [pair] step). The foreground service is started by the
     * [connectionState] observer once a session forms, not here -- see the init block. On a device that
     * cannot advertise, the flow completes immediately and [pairingFault] reports PERIPHERAL_UNSUPPORTED.
     */
    fun startAdvertising() {
        cancelAdvertiseJob()
        _isAdvertising.value = true
        advertiseJob = viewModelScope.launch {
            try {
                // Collecting keeps advertising alive; emissions signal the pump connected, after which
                // the manager owns the lifecycle. We only need to hold the flow open here.
                pumpScanner.scan().collect { }
            } finally {
                _isAdvertising.value = false
            }
        }
    }

    /** Cancel advertise-and-wait before a session forms. The foreground service is only ever started
     * once a session forms (see init), so there is nothing to stop here. */
    fun stopAdvertising() {
        cancelAdvertiseJob()
        _isAdvertising.value = false
    }

    private fun cancelAdvertiseJob() {
        advertiseJob?.cancel()
        advertiseJob = null
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
        cancelAdvertiseJob()
    }

    private companion object {
        /** Connection states where a session is live or actively forming -- the service must keep running. */
        val SESSION_LIVE_OR_FORMING = setOf(
            ConnectionState.CONNECTING,
            ConnectionState.AUTHENTICATING,
            ConnectionState.CONNECTED,
        )
    }
}
