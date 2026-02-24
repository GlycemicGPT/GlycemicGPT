package com.glycemicgpt.mobile.domain.model

/**
 * A device discovered during scanning. Generalizes [DiscoveredPump] to
 * support any plugin-discoverable device (pumps, CGMs, BGMs, etc.).
 */
data class DiscoveredDevice(
    val name: String,
    val address: String,
    val rssi: Int? = null,
    val pluginId: String,
    val metadata: Map<String, String> = emptyMap(),
)
