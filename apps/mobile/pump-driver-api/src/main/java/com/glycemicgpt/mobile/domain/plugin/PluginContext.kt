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
 * **Security note:** [androidContext] exposes the full application [Context].
 * This is acceptable for compile-time plugins living in the monorepo, but
 * MUST be replaced with a restricted interface before any runtime-loaded
 * (third-party) plugin support is introduced. See Phase 4c in the plan.
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
