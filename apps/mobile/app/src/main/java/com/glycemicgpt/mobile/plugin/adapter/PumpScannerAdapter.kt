package com.glycemicgpt.mobile.plugin.adapter

import com.glycemicgpt.mobile.domain.model.DiscoveredPump
import com.glycemicgpt.mobile.domain.pump.PumpScanner
import com.glycemicgpt.mobile.plugin.PluginRegistry
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.map
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Bridges the deprecated [PumpScanner] interface to the plugin registry.
 */
@Suppress("DEPRECATION")
@Singleton
class PumpScannerAdapter @Inject constructor(
    private val registry: PluginRegistry,
) : PumpScanner {

    override fun scan(): Flow<DiscoveredPump> {
        val plugin = registry.activePumpPlugin.value ?: return emptyFlow()
        return plugin.scan().map { device ->
            DiscoveredPump(
                name = device.name,
                address = device.address,
                rssi = device.rssi ?: 0,
            )
        }
    }
}
