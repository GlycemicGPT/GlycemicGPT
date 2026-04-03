package com.glycemicgpt.mobile.plugin

import android.content.Context
import android.content.SharedPreferences
import com.glycemicgpt.mobile.domain.plugin.PluginCapability
import dagger.hilt.android.qualifiers.ApplicationContext
import java.util.Locale
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Tracks which plugin IDs are active per capability slot.
 * Persisted via SharedPreferences so active plugins restore on app launch.
 */
@Singleton
class PluginPreferences @Inject constructor(
    @ApplicationContext context: Context,
) {
    private val prefs: SharedPreferences =
        context.getSharedPreferences("plugin_prefs", Context.MODE_PRIVATE)

    fun getActivePluginId(capability: PluginCapability): String? =
        prefs.getString(keyFor(capability), null)

    fun setActivePluginId(capability: PluginCapability, pluginId: String) {
        prefs.edit().putString(keyFor(capability), pluginId).apply()
    }

    fun clearActivePlugin(capability: PluginCapability) {
        prefs.edit().remove(keyFor(capability)).apply()
    }

    /** Get all plugin IDs currently active for multi-instance capabilities. */
    fun getActivePluginIds(capability: PluginCapability): Set<String> =
        prefs.getStringSet(multiKeyFor(capability), emptySet())?.toSet() ?: emptySet()

    @Synchronized
    fun addActivePluginId(capability: PluginCapability, pluginId: String) {
        val current = getActivePluginIds(capability).toMutableSet()
        current.add(pluginId)
        prefs.edit().putStringSet(multiKeyFor(capability), current).apply()
    }

    @Synchronized
    fun removeActivePluginId(capability: PluginCapability, pluginId: String) {
        val current = getActivePluginIds(capability).toMutableSet()
        current.remove(pluginId)
        prefs.edit().putStringSet(multiKeyFor(capability), current).apply()
    }

    /** Get the set of installed runtime plugin IDs. */
    fun getInstalledRuntimePluginIds(): Set<String> =
        prefs.getStringSet(KEY_RUNTIME_PLUGINS, emptySet())?.toSet() ?: emptySet()

    /** Add a runtime plugin ID to the installed set. */
    @Synchronized
    fun addInstalledRuntimePlugin(pluginId: String) {
        val current = getInstalledRuntimePluginIds().toMutableSet()
        current.add(pluginId)
        prefs.edit().putStringSet(KEY_RUNTIME_PLUGINS, current).apply()
    }

    /** Remove a runtime plugin ID from the installed set. */
    @Synchronized
    fun removeInstalledRuntimePlugin(pluginId: String) {
        val current = getInstalledRuntimePluginIds().toMutableSet()
        current.remove(pluginId)
        prefs.edit().putStringSet(KEY_RUNTIME_PLUGINS, current).apply()
    }

    @Synchronized
    fun clear() {
        prefs.edit().clear().apply()
    }

    private fun keyFor(capability: PluginCapability): String =
        "active_${capability.name.lowercase(Locale.ROOT)}"

    private fun multiKeyFor(capability: PluginCapability): String =
        "active_multi_${capability.name.lowercase(Locale.ROOT)}"

    companion object {
        private const val KEY_RUNTIME_PLUGINS = "installed_runtime_plugins"
    }
}
