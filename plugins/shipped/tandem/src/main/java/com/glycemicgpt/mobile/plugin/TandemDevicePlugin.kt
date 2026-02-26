package com.glycemicgpt.mobile.plugin

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
import com.glycemicgpt.mobile.domain.plugin.ui.ButtonStyle
import com.glycemicgpt.mobile.ble.connection.BleConnectionManager
import com.glycemicgpt.mobile.ble.connection.BleScanner
import com.glycemicgpt.mobile.ble.connection.TandemBleDriver
import com.glycemicgpt.mobile.ble.messages.TandemHistoryLogParser
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map
import kotlin.reflect.KClass

class TandemDevicePlugin(
    private val connectionManager: BleConnectionManager,
    private val bleDriver: TandemBleDriver,
    private val scanner: BleScanner,
    private val historyParser: TandemHistoryLogParser,
) : DevicePlugin {

    override val metadata = METADATA

    override val capabilities: Set<PluginCapability> = setOf(
        PluginCapability.GLUCOSE_SOURCE,
        PluginCapability.INSULIN_SOURCE,
        PluginCapability.PUMP_STATUS,
    )

    private val glucoseSource = TandemGlucoseSource(bleDriver)
    private val insulinSource = TandemInsulinSource(bleDriver)
    private val pumpStatus = TandemPumpStatus(bleDriver, historyParser, connectionManager)

    override fun initialize(context: PluginContext) {
        // No additional initialization needed; BLE components are injected ready-to-use
    }

    override fun shutdown() {
        connectionManager.disconnect()
    }

    override fun onActivated() {
        // Auto-reconnect if previously paired
        connectionManager.autoReconnectIfPaired()
    }

    override fun onDeactivated() {
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

    override fun connect(address: String, config: Map<String, String>) {
        connectionManager.connect(address, config["pairingCode"])
    }

    override fun disconnect() {
        connectionManager.disconnect()
    }

    override fun scan(): Flow<DiscoveredDevice> =
        scanner.scan().map { pump ->
            DiscoveredDevice(
                name = pump.name,
                address = pump.address,
                rssi = pump.rssi,
                pluginId = PLUGIN_ID,
            )
        }

    override fun settingsDescriptor(): PluginSettingsDescriptor = PluginSettingsDescriptor(
        sections = listOf(
            PluginSettingsSection(
                title = "Connection",
                items = listOf(
                    SettingDescriptor.InfoText(
                        key = "pairing_status",
                        text = "Status: ${connectionManager.connectionState.value}",
                    ),
                    SettingDescriptor.ActionButton(
                        key = "unpair",
                        label = "Unpair Pump",
                        style = ButtonStyle.DESTRUCTIVE,
                    ),
                ),
            ),
        ),
    )

    override fun observeDashboardCards(): Flow<List<DashboardCardDescriptor>> =
        flowOf(emptyList())

    companion object {
        const val PLUGIN_ID = "com.glycemicgpt.tandem"

        /** Shared metadata -- used by both [TandemDevicePlugin] and [TandemPluginFactory]. */
        val METADATA = PluginMetadata(
            id = PLUGIN_ID,
            name = "Tandem Insulin Pump",
            version = "1.0.0",
            apiVersion = PLUGIN_API_VERSION,
            description = "Tandem insulin pumps (t:slim X2, Mobi) with Dexcom CGM",
            author = "GlycemicGPT",
            protocolName = "Tandem",
        )
    }
}
