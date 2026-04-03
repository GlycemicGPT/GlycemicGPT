package com.glycemicgpt.mobile.plugin

import android.content.Context
import android.net.Uri
import com.glycemicgpt.mobile.data.local.SafetyLimitsStore
import com.glycemicgpt.mobile.domain.plugin.DevicePlugin
import com.glycemicgpt.mobile.domain.plugin.PLUGIN_API_VERSION
import com.glycemicgpt.mobile.domain.plugin.Plugin
import com.glycemicgpt.mobile.domain.plugin.PluginCapability
import com.glycemicgpt.mobile.domain.plugin.PluginContext
import com.glycemicgpt.mobile.domain.plugin.PluginFactory
import com.glycemicgpt.mobile.domain.plugin.PluginMetadata
import com.glycemicgpt.mobile.domain.plugin.PluginSettingsStore
import com.glycemicgpt.mobile.domain.pump.DebugLogger
import com.glycemicgpt.mobile.domain.plugin.events.PluginEvent
import com.glycemicgpt.mobile.domain.pump.PumpCredentialProvider
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import timber.log.Timber
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Information about a runtime-loaded plugin for UI display.
 */
data class RuntimePluginInfo(
    val metadata: PluginMetadata,
    val jarFileName: String,
    val isActive: Boolean,
)

/**
 * Central registry managing plugin lifecycle, activation, and mutual exclusion.
 *
 * Compile-time discovery: all [PluginFactory] instances are provided via Hilt
 * multibindings. At [initialize], plugins are created from factories and
 * previously-active plugins are restored from [PluginPreferences].
 */
@Singleton
class PluginRegistry @Inject constructor(
    private val factories: Set<@JvmSuppressWildcards PluginFactory>,
    private val preferences: PluginPreferences,
    private val eventBus: PluginEventBusImpl,
    @ApplicationContext private val context: Context,
    private val credentialProvider: PumpCredentialProvider,
    private val debugLogger: DebugLogger,
    private val safetyLimitsStore: SafetyLimitsStore,
) {
    // Thread-safe maps: activation/deactivation can be triggered from
    // multiple coroutine dispatchers or UI callbacks concurrently.
    private val plugins: MutableMap<String, Plugin> = ConcurrentHashMap()
    private val activePlugins: MutableMap<String, Plugin> = ConcurrentHashMap()

    // Guards compound read-check-write sequences in activate/deactivate
    // to prevent TOCTOU races on the activePlugins map.
    private val activationLock = Any()

    private val initialized = AtomicBoolean(false)

    private val _safetyLimits = MutableStateFlow(safetyLimitsStore.toSafetyLimits())

    // Plugin settings stores (keyed by plugin ID) for access from detail screens
    private val pluginSettingsStores: MutableMap<String, PluginSettingsStoreImpl> = ConcurrentHashMap()

    // Runtime plugin support
    private val dexPluginLoader = DexPluginLoader(context)
    private val pluginFileManager = PluginFileManager(context)
    private val runtimePluginJars: MutableMap<String, File> = ConcurrentHashMap()
    private val compileTimePluginIds: MutableSet<String> = ConcurrentHashMap.newKeySet()

    private val _availablePlugins = MutableStateFlow<List<PluginMetadata>>(emptyList())
    val availablePlugins: StateFlow<List<PluginMetadata>> = _availablePlugins.asStateFlow()

    private val _activePumpPlugin = MutableStateFlow<DevicePlugin?>(null)
    val activePumpPlugin: StateFlow<DevicePlugin?> = _activePumpPlugin.asStateFlow()

    private val _activeGlucoseSource = MutableStateFlow<DevicePlugin?>(null)
    val activeGlucoseSource: StateFlow<DevicePlugin?> = _activeGlucoseSource.asStateFlow()

    private val _activeCalibrationTarget = MutableStateFlow<DevicePlugin?>(null)
    val activeCalibrationTarget: StateFlow<DevicePlugin?> = _activeCalibrationTarget.asStateFlow()

    private val _activeDataSyncPlugins = MutableStateFlow<Set<Plugin>>(emptySet())
    val activeDataSyncPlugins: StateFlow<Set<Plugin>> = _activeDataSyncPlugins.asStateFlow()

    private val _activeBgmSources = MutableStateFlow<Set<DevicePlugin>>(emptySet())
    val activeBgmSources: StateFlow<Set<DevicePlugin>> = _activeBgmSources.asStateFlow()

    private val _allActivePlugins = MutableStateFlow<List<Plugin>>(emptyList())
    val allActivePlugins: StateFlow<List<Plugin>> = _allActivePlugins.asStateFlow()

    private val _runtimePlugins = MutableStateFlow<List<RuntimePluginInfo>>(emptyList())
    val runtimePlugins: StateFlow<List<RuntimePluginInfo>> = _runtimePlugins.asStateFlow()

    /**
     * Initialize the registry: create plugins from factories and restore
     * previously active plugins from preferences. Called from Application.onCreate.
     */
    fun initialize() {
        check(initialized.compareAndSet(false, true)) { "PluginRegistry already initialized" }
        Timber.d("PluginRegistry: initializing with %d factories", factories.size)

        // Create all plugins from compile-time factories; one bad plugin must not break the rest.
        for (factory in factories) {
            val meta = factory.metadata
            if (meta.apiVersion != PLUGIN_API_VERSION) {
                Timber.w(
                    "Plugin %s has API version %d, expected %d -- skipping",
                    meta.id, meta.apiVersion, PLUGIN_API_VERSION,
                )
                continue
            }
            try {
                validatePluginId(meta.id)
                // Reserve the ID before init so a runtime plugin can't hijack
                // a built-in ID if the built-in's init fails transiently.
                compileTimePluginIds.add(meta.id)
                val pluginContext = createPluginContext(meta.id)
                val plugin = factory.create(pluginContext)
                plugin.initialize(pluginContext)
                plugins[meta.id] = plugin
                Timber.d("Plugin created: %s (%s)", meta.name, meta.id)
            } catch (e: Exception) {
                Timber.e(e, "Plugin %s failed to create/initialize -- skipping", meta.id)
                pluginSettingsStores.remove(meta.id)
            }
        }

        // Discover runtime plugins from JAR files
        discoverRuntimePlugins()

        _availablePlugins.value = plugins.values.map { it.metadata }

        // Restore active plugins from preferences
        restoreActivePlugins()
    }

    /**
     * Activate a plugin by ID. Handles mutual exclusion: if the plugin has
     * single-instance capabilities that conflict with an already-active plugin,
     * the new plugin is activated first (so the capability slot is never empty),
     * then the conflicting plugin is deactivated.
     */
    fun activatePlugin(pluginId: String): Result<Unit> = synchronized(activationLock) {
        val plugin = plugins[pluginId]
            ?: return Result.failure(IllegalArgumentException("Unknown plugin: $pluginId"))

        // Idempotent: already active, nothing to do
        if (pluginId in activePlugins) {
            Timber.d("Plugin %s is already active, skipping activation", pluginId)
            return Result.success(Unit)
        }

        // Collect conflicting plugins before activation
        val conflictingIds = mutableSetOf<String>()
        for (cap in plugin.capabilities) {
            if (cap in PluginCapability.SINGLE_INSTANCE) {
                val existingId = preferences.getActivePluginId(cap)
                if (existingId != null && existingId != pluginId) {
                    conflictingIds.add(existingId)
                }
            }
        }

        // Activate new plugin first (slot is never empty)
        try {
            plugin.onActivated()
        } catch (e: Exception) {
            Timber.e(e, "Plugin %s failed to activate", pluginId)
            return Result.failure(e)
        }
        activePlugins[pluginId] = plugin

        // Persist and update state flows
        for (cap in plugin.capabilities) {
            if (cap in PluginCapability.SINGLE_INSTANCE) {
                preferences.setActivePluginId(cap, pluginId)
            } else {
                preferences.addActivePluginId(cap, pluginId)
            }
        }

        // Now deactivate conflicts (old plugins) after new one is active
        for (conflictId in conflictingIds) {
            deactivatePluginInternal(conflictId)
        }

        updateStateFlows()
        Timber.d("Plugin activated: %s", pluginId)
        Result.success(Unit)
    }

    /**
     * Deactivate a plugin by ID. Calls onDeactivated and removes from active set.
     */
    fun deactivatePlugin(pluginId: String): Result<Unit> = synchronized(activationLock) {
        deactivatePluginInternal(pluginId)
    }

    /** Internal deactivation -- caller must hold [activationLock]. */
    private fun deactivatePluginInternal(pluginId: String): Result<Unit> {
        val plugin = activePlugins.remove(pluginId)
            ?: return Result.failure(IllegalArgumentException("Plugin not active: $pluginId"))

        try {
            plugin.onDeactivated()
        } catch (e: Exception) {
            Timber.e(e, "Plugin %s threw during onDeactivated, continuing cleanup", pluginId)
        }

        // Clear preferences
        for (cap in plugin.capabilities) {
            if (cap in PluginCapability.SINGLE_INSTANCE) {
                if (preferences.getActivePluginId(cap) == pluginId) {
                    preferences.clearActivePlugin(cap)
                }
            } else {
                preferences.removeActivePluginId(cap, pluginId)
            }
        }

        updateStateFlows()
        Timber.d("Plugin deactivated: %s", pluginId)
        return Result.success(Unit)
    }

    fun getPlugin(pluginId: String): Plugin? = plugins[pluginId]

    /** Returns the settings store for a plugin, or null if not found. */
    fun getPluginSettingsStore(pluginId: String): PluginSettingsStore? = pluginSettingsStores[pluginId]

    /** Returns true if the given plugin was loaded at runtime (not compile-time). */
    fun isRuntimePlugin(pluginId: String): Boolean = pluginId in runtimePluginJars

    /**
     * Install a runtime plugin from a content URI.
     * Copies the JAR, loads it, creates the plugin with a restricted context,
     * and registers it. The plugin is not activated automatically.
     */
    fun installRuntimePlugin(uri: Uri): Result<PluginMetadata> = synchronized(activationLock) {
        // Copy JAR to plugins dir
        val jarFile = pluginFileManager.installPlugin(uri).getOrElse { e ->
            return Result.failure(e)
        }

        // Load the JAR
        val discovered = dexPluginLoader.loadJar(jarFile)
        if (discovered == null) {
            pluginFileManager.removePlugin(jarFile)
            return Result.failure(IllegalArgumentException("Failed to load plugin from JAR"))
        }

        // Validate plugin ID format
        try {
            validatePluginId(discovered.manifest.id)
        } catch (e: Exception) {
            pluginFileManager.removePlugin(jarFile)
            return Result.failure(e)
        }

        // Check for ID conflicts with compile-time plugins
        if (discovered.manifest.id in compileTimePluginIds) {
            pluginFileManager.removePlugin(jarFile)
            return Result.failure(
                IllegalArgumentException(
                    "Plugin ID '${discovered.manifest.id}' conflicts with a built-in plugin",
                ),
            )
        }

        // Check for ID conflicts with already-loaded runtime plugins
        if (discovered.manifest.id in plugins) {
            pluginFileManager.removePlugin(jarFile)
            return Result.failure(
                IllegalArgumentException(
                    "Plugin ID '${discovered.manifest.id}' is already installed",
                ),
            )
        }

        // Create the plugin with restricted context
        return try {
            val pluginContext = createRestrictedPluginContext(discovered.manifest.id)
            val plugin = discovered.factory.create(pluginContext)
            plugin.initialize(pluginContext)

            plugins[discovered.manifest.id] = plugin
            runtimePluginJars[discovered.manifest.id] = jarFile
            preferences.addInstalledRuntimePlugin(discovered.manifest.id)

            _availablePlugins.value = plugins.values.map { it.metadata }
            updateRuntimePluginsFlow()

            Timber.d(
                "Runtime plugin installed: %s v%s from %s",
                discovered.manifest.name, discovered.manifest.version, jarFile.name,
            )
            Result.success(plugin.metadata)
        } catch (e: Exception) {
            Timber.e(e, "Failed to create/initialize runtime plugin %s", discovered.manifest.id)
            pluginSettingsStores.remove(discovered.manifest.id)
            pluginFileManager.removePlugin(jarFile)
            Result.failure(e)
        }
    }

    /**
     * Remove a runtime plugin: deactivate, shutdown, delete JAR, clean preferences.
     */
    fun removeRuntimePlugin(pluginId: String): Result<Unit> = synchronized(activationLock) {
        if (pluginId !in runtimePluginJars) {
            return Result.failure(
                IllegalArgumentException("Plugin '$pluginId' is not a runtime plugin"),
            )
        }

        // Deactivate if active
        if (pluginId in activePlugins) {
            deactivatePluginInternal(pluginId).onFailure { e ->
                Timber.w(e, "Failed to deactivate plugin %s during removal, continuing", pluginId)
            }
        }

        // Shutdown and remove from registry
        val plugin = plugins.remove(pluginId)
        if (plugin != null) {
            try {
                plugin.shutdown()
            } catch (e: Exception) {
                Timber.e(e, "Plugin %s threw during shutdown, continuing cleanup", pluginId)
            }
        }

        // Delete the JAR file
        val jarFile = runtimePluginJars.remove(pluginId)
        if (jarFile != null) {
            pluginFileManager.removePlugin(jarFile)
        }

        // Clean up preferences and settings store
        preferences.removeInstalledRuntimePlugin(pluginId)
        pluginSettingsStores.remove(pluginId)

        // Delete plugin settings SharedPreferences
        context.deleteSharedPreferences("plugin_settings_$pluginId")

        _availablePlugins.value = plugins.values.map { it.metadata }
        updateRuntimePluginsFlow()

        Timber.d("Runtime plugin removed: %s", pluginId)
        return Result.success(Unit)
    }

    /**
     * Re-read safety limits from the store and push updated values to
     * all plugins via [PluginContext.safetyLimits] and the event bus.
     * Called by HomeViewModel / BackendSyncManager after a successful
     * safety-limits refresh from the backend.
     */
    fun refreshSafetyLimits() = synchronized(activationLock) {
        val updated = safetyLimitsStore.toSafetyLimits()
        _safetyLimits.value = updated
        eventBus.publishPlatform(
            PluginEvent.SafetyLimitsChanged(
                pluginId = PLATFORM_PLUGIN_ID,
                limits = updated,
            ),
        )
        Timber.d("PluginRegistry: safety limits refreshed -> %s", updated)
    }

    private fun restoreActivePlugins() = synchronized(activationLock) {
        // Restore single-instance capabilities
        for (cap in PluginCapability.SINGLE_INSTANCE) {
            val pluginId = preferences.getActivePluginId(cap) ?: continue
            val plugin = plugins[pluginId] ?: continue
            if (pluginId !in activePlugins) {
                try {
                    plugin.onActivated()
                    activePlugins[pluginId] = plugin
                } catch (e: Exception) {
                    Timber.e(e, "Failed to restore plugin %s for %s, clearing preference", pluginId, cap)
                    preferences.clearActivePlugin(cap)
                }
            }
        }

        // Restore multi-instance capabilities
        for (cap in PluginCapability.MULTI_INSTANCE) {
            for (pluginId in preferences.getActivePluginIds(cap)) {
                val plugin = plugins[pluginId] ?: continue
                if (pluginId !in activePlugins) {
                    try {
                        plugin.onActivated()
                        activePlugins[pluginId] = plugin
                    } catch (e: Exception) {
                        Timber.e(e, "Failed to restore plugin %s for %s, clearing preference", pluginId, cap)
                        preferences.removeActivePluginId(cap, pluginId)
                    }
                }
            }
        }

        updateStateFlows()
    }

    private fun updateStateFlows() {
        _allActivePlugins.value = activePlugins.values.toList()

        // Single-instance slots
        _activePumpPlugin.value = activePlugins.values.firstOrNull { plugin ->
            PluginCapability.PUMP_STATUS in plugin.capabilities ||
                PluginCapability.INSULIN_SOURCE in plugin.capabilities
        } as? DevicePlugin

        _activeGlucoseSource.value = activePlugins.values.firstOrNull { plugin ->
            PluginCapability.GLUCOSE_SOURCE in plugin.capabilities
        } as? DevicePlugin

        _activeCalibrationTarget.value = activePlugins.values.firstOrNull { plugin ->
            PluginCapability.CALIBRATION_TARGET in plugin.capabilities
        } as? DevicePlugin

        // Multi-instance slots
        _activeBgmSources.value = activePlugins.values
            .filter { PluginCapability.BGM_SOURCE in it.capabilities }
            .filterIsInstance<DevicePlugin>()
            .toSet()

        _activeDataSyncPlugins.value = activePlugins.values
            .filter { PluginCapability.DATA_SYNC in it.capabilities }
            .toSet()

        updateRuntimePluginsFlow()
    }

    private fun validatePluginId(id: String) {
        require(VALID_PLUGIN_ID.matches(id)) {
            "Invalid plugin ID '$id'. Must match: letters, digits, dots, hyphens, underscores."
        }
    }

    private fun createPluginContext(pluginId: String): PluginContext {
        val settingsStore = PluginSettingsStoreImpl(context, pluginId)
        pluginSettingsStores[pluginId] = settingsStore
        return PluginContext(
            androidContext = context,
            pluginId = pluginId,
            settingsStore = settingsStore,
            credentialProvider = credentialProvider,
            debugLogger = debugLogger,
            eventBus = eventBus,
            safetyLimits = _safetyLimits,
            apiVersion = PLUGIN_API_VERSION,
        )
    }

    private fun createRestrictedPluginContext(pluginId: String): PluginContext {
        val settingsStore = PluginSettingsStoreImpl(context, pluginId)
        pluginSettingsStores[pluginId] = settingsStore
        return RestrictedPluginContext.create(
            baseContext = context,
            pluginId = pluginId,
            settingsStore = settingsStore,
            debugLogger = debugLogger,
            eventBus = eventBus,
            safetyLimits = _safetyLimits,
        )
    }

    /**
     * Discover runtime plugins from JAR files on disk.
     * Called once during [initialize] after compile-time plugins are registered.
     */
    private fun discoverRuntimePlugins() {
        val discovered = dexPluginLoader.discover()
        Timber.d("PluginRegistry: discovered %d runtime plugins", discovered.size)

        for (dp in discovered) {
            val pluginId = dp.manifest.id

            // Validate plugin ID format
            try {
                validatePluginId(pluginId)
            } catch (e: Exception) {
                Timber.w(e, "Runtime plugin has invalid ID '%s' -- skipping", pluginId)
                continue
            }

            // Skip if ID conflicts with compile-time plugin
            if (pluginId in compileTimePluginIds) {
                Timber.w(
                    "Runtime plugin %s conflicts with built-in plugin -- skipping",
                    pluginId,
                )
                continue
            }

            // Skip if already registered (shouldn't happen, but be safe)
            if (pluginId in plugins) {
                Timber.w("Runtime plugin %s already registered -- skipping", pluginId)
                continue
            }

            try {
                val pluginContext = createRestrictedPluginContext(pluginId)
                val plugin = dp.factory.create(pluginContext)
                plugin.initialize(pluginContext)

                plugins[pluginId] = plugin
                runtimePluginJars[pluginId] = dp.jarFile
                preferences.addInstalledRuntimePlugin(pluginId)

                Timber.d(
                    "Runtime plugin loaded: %s (%s) from %s",
                    dp.manifest.name, pluginId, dp.jarFile.name,
                )
            } catch (e: Exception) {
                Timber.e(e, "Runtime plugin %s failed to create/initialize -- skipping", pluginId)
                pluginSettingsStores.remove(pluginId)
            }
        }

        updateRuntimePluginsFlow()
    }

    private fun updateRuntimePluginsFlow() {
        _runtimePlugins.value = runtimePluginJars.mapNotNull { (pluginId, jarFile) ->
            val plugin = plugins[pluginId] ?: return@mapNotNull null
            RuntimePluginInfo(
                metadata = plugin.metadata,
                jarFileName = jarFile.name,
                isActive = pluginId in activePlugins,
            )
        }
    }

    companion object {
        /** Identifier used for platform-originated events (not a real plugin). */
        const val PLATFORM_PLUGIN_ID = "platform"

        /** Plugin IDs must be reverse-domain-name style: letters, digits, dots, hyphens, underscores. */
        private val VALID_PLUGIN_ID = DexPluginLoader.VALID_PLUGIN_ID
    }
}
