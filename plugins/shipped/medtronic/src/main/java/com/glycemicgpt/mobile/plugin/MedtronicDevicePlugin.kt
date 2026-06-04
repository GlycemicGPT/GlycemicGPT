/*
 * GlycemicGPT code (GPL-3.0). Read-only DevicePlugin for the Medtronic MiniMed 700-series.
 *
 * The first :app runtime surface of the Medtronic driver: it exposes the B2 peripheral-mode
 * connection manager and the C1/C2 readers (via MedtronicReadGateway) through the same capability
 * contract as Tandem. READ-ONLY -- it declares GLUCOSE_SOURCE / INSULIN_SOURCE / PUMP_STATUS only;
 * there is no PUMP_CONTROL capability in the platform and no method here writes to the pump.
 */
package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.ble.connection.MedtronicBleConnectionManager
import com.glycemicgpt.mobile.ble.read.MedtronicReadGateway
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.model.DiscoveredDevice
import com.glycemicgpt.mobile.domain.plugin.DevicePlugin
import com.glycemicgpt.mobile.domain.plugin.PLUGIN_API_VERSION
import com.glycemicgpt.mobile.domain.plugin.PluginCapability
import com.glycemicgpt.mobile.domain.plugin.PluginCapabilityInterface
import com.glycemicgpt.mobile.domain.plugin.PluginContext
import com.glycemicgpt.mobile.domain.plugin.PluginMetadata
import com.glycemicgpt.mobile.domain.plugin.capabilities.GlucoseSource
import com.glycemicgpt.mobile.domain.plugin.capabilities.InsulinSource
import com.glycemicgpt.mobile.domain.plugin.capabilities.PumpStatus
import com.glycemicgpt.mobile.domain.plugin.ui.DashboardCardDescriptor
import com.glycemicgpt.mobile.domain.plugin.ui.PluginSettingsDescriptor
import com.glycemicgpt.mobile.domain.plugin.ui.PluginSettingsSection
import com.glycemicgpt.mobile.domain.plugin.ui.SettingDescriptor
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.flowOf
import kotlin.reflect.KClass

class MedtronicDevicePlugin(
    private val connectionManager: MedtronicBleConnectionManager,
    private val gateway: MedtronicReadGateway,
) : DevicePlugin {

    override val metadata = METADATA

    override val capabilities: Set<PluginCapability> = setOf(
        PluginCapability.GLUCOSE_SOURCE,
        PluginCapability.INSULIN_SOURCE,
        PluginCapability.PUMP_STATUS,
    )

    private val glucoseSource = MedtronicGlucoseSource(gateway)
    private val insulinSource = MedtronicInsulinSource(gateway)
    private val pumpStatus = MedtronicPumpStatus(gateway, connectionManager)

    override fun initialize(context: PluginContext) {
        // BLE components are injected ready-to-use; no additional setup needed.
    }

    override fun shutdown() {
        // Terminal teardown: fully release the connection manager's worker thread + coroutine scope
        // (not just the BLE session). shutdown() is the destroy hook -- distinct from onDeactivated(),
        // which only disconnects so the plugin can be reactivated. close() is safe here because the
        // plugin is being discarded and is not re-created against the same manager.
        connectionManager.close()
    }

    override fun onActivated() {
        // Reconnect to an already-paired pump when the user selects this driver.
        connectionManager.reconnectIfPaired()
    }

    override fun onDeactivated() {
        // Drop the live session but keep the pairing (and the manager alive), so reactivating
        // reconnects without re-pairing. Use disconnect(), not close(): close() is reserved for
        // terminal shutdown().
        connectionManager.disconnect()
    }

    @Suppress("UNCHECKED_CAST")
    override fun <T : PluginCapabilityInterface> getCapability(type: KClass<T>): T? = when (type) {
        GlucoseSource::class -> glucoseSource as? T
        InsulinSource::class -> insulinSource as? T
        PumpStatus::class -> pumpStatus as? T
        else -> null
    }

    override fun observeConnectionState(): StateFlow<ConnectionState> =
        connectionManager.connectionState

    /**
     * Begin a connection. In the inverted (phone-as-peripheral) topology there is no pump address to
     * dial -- the phone advertises and the pump connects to it -- so [address] is unused; the connection
     * manager drives advertising + the SAKE handshake. Pass `config["forceFirstPair"] = "true"` to force
     * first-pair advertising when re-pairing instead of reconnecting to a remembered pump.
     */
    override fun connect(address: String, config: Map<String, String>) {
        connectionManager.startSession(forceFirstPair = config["forceFirstPair"].toBoolean())
    }

    override fun disconnect() {
        connectionManager.disconnect()
    }

    /**
     * Discovery is advertise-and-wait in the inverted topology (the pump finds us); the connection
     * manager emits a [DiscoveredDevice] when a pump connects, already stamped with the canonical
     * [PLUGIN_ID].
     */
    override fun scan(): Flow<DiscoveredDevice> =
        connectionManager.scan()

    /**
     * Pump-specific connection notes surfaced under the generic pump settings card. The card chrome
     * already renders live pairing status and the Unpair action for any active pump plugin, so the
     * descriptor only contributes what is unique to this driver: the single-peer limitation.
     */
    override fun settingsDescriptor(): PluginSettingsDescriptor = PluginSettingsDescriptor(
        sections = listOf(
            PluginSettingsSection(
                title = "Connection",
                items = listOf(
                    // Single-peer limitation (medtronic-ble-reverse-engineering.md Sec. 7): a 700-series
                    // pump talks to one phone at a time, so pairing GlycemicGPT requires first removing
                    // the pump from the official Medtronic app. Surfaced here for the pairing UX.
                    SettingDescriptor.InfoText(
                        key = "single_peer_note",
                        text = "A MiniMed pump pairs with only one phone at a time. " +
                            "Remove the pump from the official Medtronic app before pairing it here.",
                    ),
                ),
            ),
        ),
    )

    override fun observeDashboardCards(): Flow<List<DashboardCardDescriptor>> =
        flowOf(emptyList())

    companion object {
        /** Canonical plugin id; single source of truth is [MedtronicBleConnectionManager.PLUGIN_ID]. */
        const val PLUGIN_ID = MedtronicBleConnectionManager.PLUGIN_ID

        /** Shared metadata -- used by both [MedtronicDevicePlugin] and [MedtronicPluginFactory]. */
        val METADATA = PluginMetadata(
            id = PLUGIN_ID,
            name = "Medtronic MiniMed Pump",
            version = "1.0.0",
            apiVersion = PLUGIN_API_VERSION,
            description = "Medtronic MiniMed 700-series pumps (680G / 770G / 780G) over Bluetooth (read-only, BETA)",
            author = "GlycemicGPT",
            protocolName = "Medtronic",
        )
    }
}
