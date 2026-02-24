package com.glycemicgpt.mobile.domain.plugin

/** Current plugin API version. Plugins with a different version are rejected. */
const val PLUGIN_API_VERSION = 1

/**
 * Immutable metadata describing a plugin. Available before the plugin is created.
 */
data class PluginMetadata(
    /** Reverse-domain unique ID, e.g. "com.glycemicgpt.tandem". */
    val id: String,
    /** Human-readable name, e.g. "Tandem t:slim X2". */
    val name: String,
    /** Semantic version string, e.g. "1.0.0". */
    val version: String,
    /** Plugin API version this plugin was built against. */
    val apiVersion: Int,
    /** Short description of the plugin. */
    val description: String = "",
    /** Author name. */
    val author: String = "",
    /** Optional drawable resource name for the plugin icon. */
    val iconResName: String? = null,
)
