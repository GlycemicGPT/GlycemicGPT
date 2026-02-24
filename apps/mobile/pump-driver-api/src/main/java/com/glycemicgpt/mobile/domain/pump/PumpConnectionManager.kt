package com.glycemicgpt.mobile.domain.pump

import com.glycemicgpt.mobile.domain.model.ConnectionState
import kotlinx.coroutines.flow.StateFlow

/**
 * Pump connection lifecycle management.
 *
 * Decouples connection management from transport-specific implementation details,
 * allowing consumers (ViewModels, Services) to depend on this interface
 * rather than concrete transport classes.
 *
 * This interface manages the low-level connection lifecycle (connect, disconnect,
 * reconnect, unpair). [PumpDriver] manages the high-level data access (read IoB,
 * read CGM, etc.) and delegates connection operations to this interface internally.
 * Consumers that only need pump data should depend on [PumpDriver]; consumers that
 * manage the connection UI (pairing screens, debug views, foreground services)
 * should depend on this interface.
 */
@Deprecated("Use DevicePlugin for connection management. This interface will be removed in a future version.", ReplaceWith("DevicePlugin"))
interface PumpConnectionManager {

    /** Observable connection state. */
    val connectionState: StateFlow<ConnectionState>

    /**
     * Connect to a pump at the given address.
     * @param address device address in a format specific to the transport (e.g., MAC address)
     * @param pairingCode optional pairing code for initial pairing
     */
    fun connect(address: String, pairingCode: String? = null)

    /** Disconnect from the pump and stop auto-reconnect. */
    fun disconnect()

    /** Clear stored credentials, remove device bond, and disconnect. */
    fun unpair()

    /** Reconnect to previously paired pump if credentials exist. */
    fun autoReconnectIfPaired()
}
