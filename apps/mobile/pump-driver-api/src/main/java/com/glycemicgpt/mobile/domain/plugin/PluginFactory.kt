package com.glycemicgpt.mobile.domain.plugin

/**
 * Factory for creating plugin instances. Each plugin module provides one factory
 * bound into the Hilt multibinding set. The platform discovers all factories at
 * compile time and creates plugins on demand.
 */
interface PluginFactory {
    /** Metadata available before the plugin is instantiated. */
    val metadata: PluginMetadata

    /** Create a new plugin instance with the given platform context. */
    fun create(context: PluginContext): Plugin
}
