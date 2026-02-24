package com.glycemicgpt.mobile.plugin.adapter

import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.plugin.asPumpStatus
import com.glycemicgpt.mobile.domain.pump.PumpConnectionManager
import com.glycemicgpt.mobile.plugin.PluginRegistry
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.stateIn
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Bridges the deprecated [PumpConnectionManager] interface to the plugin registry.
 */
@Suppress("DEPRECATION")
@OptIn(ExperimentalCoroutinesApi::class)
@Singleton
class PumpConnectionAdapter @Inject constructor(
    private val registry: PluginRegistry,
) : PumpConnectionManager {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    override val connectionState: StateFlow<ConnectionState> =
        registry.activePumpPlugin.flatMapLatest { plugin ->
            plugin?.observeConnectionState() ?: flowOf(ConnectionState.DISCONNECTED)
        }.stateIn(scope, SharingStarted.Eagerly, ConnectionState.DISCONNECTED)

    override fun connect(address: String, pairingCode: String?) {
        val plugin = registry.activePumpPlugin.value
        if (plugin == null) {
            Timber.w("connect() called but no active pump plugin")
            return
        }
        val config = if (pairingCode != null) mapOf("pairingCode" to pairingCode) else emptyMap()
        plugin.connect(address, config)
    }

    override fun disconnect() {
        registry.activePumpPlugin.value?.disconnect()
    }

    override fun unpair() {
        registry.activePumpPlugin.value?.asPumpStatus()?.unpair()
    }

    override fun autoReconnectIfPaired() {
        registry.activePumpPlugin.value?.asPumpStatus()?.autoReconnectIfPaired()
    }
}
