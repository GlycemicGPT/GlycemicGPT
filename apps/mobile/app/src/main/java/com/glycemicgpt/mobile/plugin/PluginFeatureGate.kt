package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.BuildConfig
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Decides whether a compile-time plugin may be registered. A gated-off plugin is never created, so it
 * is absent from Available Plugins (not selectable), has no pairing entry, and is never polled --
 * fully invisible and inert. This is the mobile analogue of the backend's per-integration kill
 * switches (e.g. `MEDTRONIC_CONNECT_ENABLED`): default-on, only an explicitly-disabled plugin is
 * gated out.
 */
fun interface PluginFeatureGate {
    fun isEnabled(pluginId: String): Boolean
}

/**
 * [PluginFeatureGate] backed by build-time flags. The Medtronic read-only BLE driver ships BETA and
 * is gated by [BuildConfig.MEDTRONIC_DRIVER_ENABLED] (default true; build with
 * `MEDTRONIC_DRIVER_ENABLED=false` to ship it off). Every other plugin is always enabled.
 */
@Singleton
class BuildConfigPluginFeatureGate @Inject constructor() : PluginFeatureGate {
    override fun isEnabled(pluginId: String): Boolean = when (pluginId) {
        // Reference the canonical id directly so the gate can never silently drift off the driver's
        // own id (which would leave the kill switch matching nothing -> always enabled).
        MedtronicDevicePlugin.PLUGIN_ID -> BuildConfig.MEDTRONIC_DRIVER_ENABLED
        else -> true
    }
}
