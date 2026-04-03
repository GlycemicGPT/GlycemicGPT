package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.domain.plugin.Plugin
import com.glycemicgpt.mobile.domain.plugin.PluginContext
import com.glycemicgpt.mobile.domain.plugin.PluginFactory
import com.glycemicgpt.mobile.ble.connection.BleConnectionManager
import com.glycemicgpt.mobile.ble.connection.BleScanner
import com.glycemicgpt.mobile.ble.connection.TandemBleDriver
import com.glycemicgpt.mobile.ble.messages.TandemHistoryLogParser
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class TandemPluginFactory @Inject constructor(
    private val connectionManager: BleConnectionManager,
    private val bleDriver: TandemBleDriver,
    private val scanner: BleScanner,
    private val historyParser: TandemHistoryLogParser,
) : PluginFactory {

    override val metadata = TandemDevicePlugin.METADATA

    override fun create(context: PluginContext): Plugin {
        return TandemDevicePlugin(connectionManager, bleDriver, scanner, historyParser)
    }
}
