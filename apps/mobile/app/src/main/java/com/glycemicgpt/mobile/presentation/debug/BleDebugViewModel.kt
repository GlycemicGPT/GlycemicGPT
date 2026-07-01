package com.glycemicgpt.mobile.presentation.debug

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.glycemicgpt.mobile.BuildConfig
import com.glycemicgpt.mobile.data.local.BleDebugStore
import com.glycemicgpt.mobile.data.repository.PumpDataRepository
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.pump.PumpConnectionManager
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import java.time.Instant
import javax.inject.Inject

@HiltViewModel
class BleDebugViewModel @Inject constructor(
    private val debugStore: BleDebugStore,
    private val connectionManager: PumpConnectionManager,
    private val pumpDataRepository: PumpDataRepository,
) : ViewModel() {

    val entries: StateFlow<List<BleDebugStore.Entry>> = debugStore.entries
    val connectionState: StateFlow<ConnectionState> = connectionManager.connectionState

    fun clearEntries() {
        debugStore.clear()
    }

    /**
     * Debug-only (reusable debug harness): write a fresh synthetic CGM reading to the Room
     * cache so the emulator — which has no live pump feed — can render the glucose hero and, combined
     * with the "Fast staleness" toggle, exercise the FRESH → STALE → TOO_STALE de-emphasis path.
     */
    fun injectTestCgm() {
        // Defense-in-depth: this writes to the same Room cache that drives the real glucose hero, so
        // hard-gate it to debug the same way the sibling fault-injection settings are, not just via
        // the debug-only navigation to this screen.
        if (!BuildConfig.DEBUG) return
        viewModelScope.launch {
            pumpDataRepository.saveCgm(
                CgmReading(
                    glucoseMgDl = TEST_CGM_MG_DL,
                    trendArrow = CgmTrend.FLAT,
                    timestamp = Instant.now(),
                ),
            )
        }
    }

    private companion object {
        const val TEST_CGM_MG_DL = 120
    }
}
