package com.glycemicgpt.mobile.domain.plugin

import android.content.Context
import com.glycemicgpt.mobile.domain.pump.DebugLogger
import com.glycemicgpt.mobile.domain.pump.PumpCredentialProvider
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import com.glycemicgpt.mobile.domain.plugin.events.PluginEventBus
import kotlinx.coroutines.flow.StateFlow

/**
 * Context provided by the platform to each plugin during initialization.
 * Gives plugins access to platform services without coupling to app internals.
 *
 * **Security note:** For compile-time plugins, [androidContext] exposes the full
 * application [Context]. For runtime-loaded plugins, [androidContext] is a
 * restricted wrapper that blocks app-scope escape vectors (startActivity,
 * startService, sendBroadcast, getSharedPreferences, etc.) while allowing
 * hardware access via an allowlisted [Context.getSystemService] set.
 */
class PluginContext(
    val androidContext: Context,
    val pluginId: String,
    val settingsStore: PluginSettingsStore,
    val credentialProvider: PumpCredentialProvider,
    val debugLogger: DebugLogger,
    val eventBus: PluginEventBus,
    /** Current safety limits; plugins must respect these as read-only constraints. */
    val safetyLimits: StateFlow<SafetyLimits>,
    val apiVersion: Int,
)
