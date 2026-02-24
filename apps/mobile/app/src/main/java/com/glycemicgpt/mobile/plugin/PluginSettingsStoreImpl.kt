package com.glycemicgpt.mobile.plugin

import android.content.Context
import android.content.SharedPreferences
import com.glycemicgpt.mobile.domain.plugin.PluginSettingsStore

/**
 * Per-plugin key-value store backed by SharedPreferences.
 * Keys are namespaced by plugin ID to prevent collisions.
 *
 * Note: this store is for general plugin settings (not credentials).
 * Sensitive credentials should be stored via [PumpCredentialProvider]
 * which uses EncryptedSharedPreferences.
 */
class PluginSettingsStoreImpl(
    context: Context,
    private val pluginId: String,
) : PluginSettingsStore {

    private val prefs: SharedPreferences =
        context.getSharedPreferences("plugin_settings_$pluginId", Context.MODE_PRIVATE)

    override fun getString(key: String, default: String): String =
        prefs.getString(key, default) ?: default

    override fun putString(key: String, value: String) {
        prefs.edit().putString(key, value).apply()
    }

    override fun getBoolean(key: String, default: Boolean): Boolean =
        prefs.getBoolean(key, default)

    override fun putBoolean(key: String, value: Boolean) {
        prefs.edit().putBoolean(key, value).apply()
    }

    override fun getInt(key: String, default: Int): Int =
        prefs.getInt(key, default)

    override fun putInt(key: String, value: Int) {
        prefs.edit().putInt(key, value).apply()
    }

    override fun getFloat(key: String, default: Float): Float =
        prefs.getFloat(key, default)

    override fun putFloat(key: String, value: Float) {
        prefs.edit().putFloat(key, value).apply()
    }

    override fun remove(key: String) {
        prefs.edit().remove(key).apply()
    }
}
