package com.glycemicgpt.mobile.plugin.adapter

/**
 * Thrown by legacy adapter methods when no plugin is currently active
 * for the requested capability.
 */
class NoActivePluginException(
    message: String = "No active plugin for this capability",
) : Exception(message)
