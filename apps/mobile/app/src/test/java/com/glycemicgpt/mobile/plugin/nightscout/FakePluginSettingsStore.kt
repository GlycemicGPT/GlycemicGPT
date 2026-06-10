package com.glycemicgpt.mobile.plugin.nightscout

import com.glycemicgpt.mobile.domain.plugin.PluginSettingsStore

/** Minimal in-memory [PluginSettingsStore] for exercising the Nightscout plugin without Android. */
internal class FakePluginSettingsStore : PluginSettingsStore {
    private val strings = mutableMapOf<String, String>()
    private val booleans = mutableMapOf<String, Boolean>()
    private val ints = mutableMapOf<String, Int>()
    private val floats = mutableMapOf<String, Float>()

    override fun getString(key: String, default: String) = strings[key] ?: default
    override fun putString(key: String, value: String) { strings[key] = value }
    override fun getBoolean(key: String, default: Boolean) = booleans[key] ?: default
    override fun putBoolean(key: String, value: Boolean) { booleans[key] = value }
    override fun getInt(key: String, default: Int) = ints[key] ?: default
    override fun putInt(key: String, value: Int) { ints[key] = value }
    override fun getFloat(key: String, default: Float) = floats[key] ?: default
    override fun putFloat(key: String, value: Float) { floats[key] = value }
    override fun remove(key: String) {
        strings.remove(key); booleans.remove(key); ints.remove(key); floats.remove(key)
    }
}
