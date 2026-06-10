/*
 * GlycemicGPT code (GPL-3.0). PluginFactory for the Medtronic MiniMed 700-series read-only driver.
 */
package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.ble.connection.MedtronicBleConnectionManager
import com.glycemicgpt.mobile.ble.read.MedtronicReadGateway
import com.glycemicgpt.mobile.domain.plugin.Plugin
import com.glycemicgpt.mobile.domain.plugin.PluginContext
import com.glycemicgpt.mobile.domain.plugin.PluginFactory
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class MedtronicPluginFactory @Inject constructor(
    private val connectionManager: MedtronicBleConnectionManager,
    private val gateway: MedtronicReadGateway,
) : PluginFactory {

    override val metadata = MedtronicDevicePlugin.METADATA

    override fun create(context: PluginContext): Plugin {
        return MedtronicDevicePlugin(connectionManager, gateway)
    }
}
