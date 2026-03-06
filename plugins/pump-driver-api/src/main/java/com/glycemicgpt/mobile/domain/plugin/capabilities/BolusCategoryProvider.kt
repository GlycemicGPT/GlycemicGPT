package com.glycemicgpt.mobile.domain.plugin.capabilities

import com.glycemicgpt.mobile.domain.plugin.PluginCapabilityInterface

/**
 * Capability for plugins that declare pump-specific bolus categories.
 *
 * Plugins use this to declare their pump's native bolus category labels and
 * map them to the platform's standard [BolusCategory] names. This enables
 * pump-agnostic insulin summaries while preserving pump-specific detail.
 *
 * Example: Tandem "CONTROL_IQ" -> platform "AUTO_CORRECTION".
 */
interface BolusCategoryProvider : PluginCapabilityInterface {
    /** The set of pump-specific category names this plugin declares. */
    fun declaredCategories(): Set<String>

    /**
     * Map a pump-specific category name to a platform-standard category name.
     *
     * @param pluginCategory One of the values from [declaredCategories].
     * @return The platform category name (matching a [BolusCategory] enum name),
     *         or null if the category is unknown.
     */
    fun toPlatformCategory(pluginCategory: String): String?
}
