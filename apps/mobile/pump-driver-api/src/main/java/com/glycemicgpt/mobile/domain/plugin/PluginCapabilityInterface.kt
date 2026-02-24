package com.glycemicgpt.mobile.domain.plugin

/**
 * Marker interface for plugin capability interfaces.
 *
 * All capability interfaces (GlucoseSource, InsulinSource, PumpStatus, etc.)
 * extend this marker so plugins can return them from [Plugin.getCapability].
 */
interface PluginCapabilityInterface
