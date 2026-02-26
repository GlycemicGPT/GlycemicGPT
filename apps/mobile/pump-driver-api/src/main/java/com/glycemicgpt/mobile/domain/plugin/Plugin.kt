package com.glycemicgpt.mobile.domain.plugin

import com.glycemicgpt.mobile.domain.plugin.capabilities.BgmSource
import com.glycemicgpt.mobile.domain.plugin.capabilities.CalibrationTarget
import com.glycemicgpt.mobile.domain.plugin.capabilities.GlucoseSource
import com.glycemicgpt.mobile.domain.plugin.capabilities.InsulinSource
import com.glycemicgpt.mobile.domain.plugin.capabilities.PumpStatus
import com.glycemicgpt.mobile.domain.plugin.ui.DashboardCardDescriptor
import com.glycemicgpt.mobile.domain.plugin.ui.DetailScreenDescriptor
import com.glycemicgpt.mobile.domain.plugin.ui.PluginSettingsDescriptor
import kotlinx.coroutines.flow.Flow
import kotlin.reflect.KClass

/**
 * Base interface for all plugins (device and non-device).
 *
 * Plugins declare their capabilities and provide typed access to each
 * capability interface via [getCapability]. The platform uses these to
 * enforce mutual-exclusion, route data, and render UI.
 */
interface Plugin {
    val metadata: PluginMetadata
    val capabilities: Set<PluginCapability>

    /** Called once after creation. Set up resources using the provided context. */
    fun initialize(context: PluginContext)

    /** Called when the plugin is being destroyed. Release all resources. */
    fun shutdown()

    /** Called when the user selects this plugin as the active one for its capabilities. */
    fun onActivated()

    /** Called when another plugin replaces this one or the user deactivates it. */
    fun onDeactivated()

    /** Declarative description of the plugin's settings UI. */
    fun settingsDescriptor(): PluginSettingsDescriptor

    /** Observable list of dashboard cards this plugin contributes. */
    fun observeDashboardCards(): Flow<List<DashboardCardDescriptor>>

    /** Get a typed capability interface, or null if this plugin doesn't support it. */
    fun <T : PluginCapabilityInterface> getCapability(type: KClass<T>): T?

    /**
     * Returns a Flow of detail screen content for the given card, or null if
     * the card has no detail view. Only called when the user taps a card with
     * [DashboardCardDescriptor.hasDetail] set to true.
     *
     * Default returns null (no detail screen). Override to provide interactive
     * detail views for specific cards.
     */
    fun observeDetailScreen(cardId: String): Flow<DetailScreenDescriptor>? = null

    /**
     * Called when the user triggers an action on the detail screen
     * (e.g., tapping an ActionButton). Same pattern as settings onAction.
     */
    fun onDetailAction(cardId: String, actionKey: String) { }
}

/** Convenience: get this plugin's [GlucoseSource] capability, if available. */
fun Plugin.asGlucoseSource(): GlucoseSource? = getCapability(GlucoseSource::class)

/** Convenience: get this plugin's [InsulinSource] capability, if available. */
fun Plugin.asInsulinSource(): InsulinSource? = getCapability(InsulinSource::class)

/** Convenience: get this plugin's [PumpStatus] capability, if available. */
fun Plugin.asPumpStatus(): PumpStatus? = getCapability(PumpStatus::class)

/** Convenience: get this plugin's [BgmSource] capability, if available. */
fun Plugin.asBgmSource(): BgmSource? = getCapability(BgmSource::class)

/** Convenience: get this plugin's [CalibrationTarget] capability, if available. */
fun Plugin.asCalibrationTarget(): CalibrationTarget? = getCapability(CalibrationTarget::class)
