package com.glycemicgpt.mobile.domain.plugin

import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.model.DiscoveredDevice
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow

/**
 * Extension of [Plugin] for plugins that connect to hardware devices via BLE
 * or other transports. Adds connection lifecycle and device scanning.
 */
interface DevicePlugin : Plugin {
    /** Observable connection state for this device plugin. */
    fun observeConnectionState(): StateFlow<ConnectionState>

    /**
     * Connect to a device at the given address. Optional config for pairing codes, etc.
     *
     * Implementations must enforce a reasonable timeout (typically 30 seconds)
     * and not block indefinitely. The connection attempt should fail with an
     * appropriate error if the device is unreachable within the timeout.
     */
    fun connect(address: String, config: Map<String, String> = emptyMap())

    /**
     * Disconnect from the currently connected device.
     * Must be safe to call even if not currently connected (no-op in that case).
     */
    fun disconnect()

    /**
     * Scan for discoverable devices compatible with this plugin.
     * The returned flow completes when scanning ends (typically after a timeout).
     * Callers should cancel collection to stop scanning early.
     */
    fun scan(): Flow<DiscoveredDevice>
}
