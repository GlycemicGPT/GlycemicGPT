package com.glycemicgpt.mobile.plugin

import android.content.Context
import com.glycemicgpt.mobile.domain.plugin.PLUGIN_API_VERSION
import com.glycemicgpt.mobile.domain.plugin.PluginFactory
import dalvik.system.DexClassLoader
import timber.log.Timber
import java.io.File

/**
 * Result of discovering a runtime plugin from a JAR file.
 */
data class DiscoveredPlugin(
    val factory: PluginFactory,
    val manifest: PluginManifest,
    val jarFile: File,
)

/**
 * Scans the plugins directory for JAR files, loads each via [DexClassLoader],
 * reads the `META-INF/plugin.json` manifest, validates API version and plugin
 * ID format, and instantiates the [PluginFactory].
 *
 * Each JAR must contain:
 * - DEX bytecode (produced by d8/R8 from compiled .class files)
 * - `META-INF/plugin.json` manifest declaring the factory class
 * - A no-arg constructor on the factory class
 */
class DexPluginLoader(private val context: Context) {

    private val pluginsDir: File
        get() = File(context.filesDir, PLUGINS_DIR_NAME)

    private val dexOutputDir: File
        get() = File(context.codeCacheDir, DEX_OUTPUT_DIR_NAME)

    /**
     * Scan the plugins directory and attempt to load each JAR.
     * Returns a list of successfully discovered plugins. Failures are logged
     * but do not prevent other plugins from loading.
     */
    fun discover(): List<DiscoveredPlugin> {
        val dir = pluginsDir
        if (!dir.exists() || !dir.isDirectory) {
            Timber.d("DexPluginLoader: plugins directory does not exist: %s", dir.absolutePath)
            return emptyList()
        }

        val dexOut = dexOutputDir
        if (!dexOut.exists()) {
            dexOut.mkdirs()
        }

        val jars = dir.listFiles { file -> file.extension == "jar" } ?: return emptyList()
        Timber.d("DexPluginLoader: found %d JAR files in %s", jars.size, dir.absolutePath)

        return jars.mapNotNull { jar -> loadJar(jar, dexOut) }
    }

    /**
     * Load a single JAR file and return a [DiscoveredPlugin] or null on failure.
     */
    fun loadJar(jarFile: File, dexOutputDir: File? = null): DiscoveredPlugin? {
        val dexOut = dexOutputDir ?: this.dexOutputDir.also { if (!it.exists()) it.mkdirs() }

        return try {
            val classLoader = DexClassLoader(
                jarFile.absolutePath,
                dexOut.absolutePath,
                null,
                context.classLoader,
            )

            val manifest = readManifest(classLoader, jarFile)
                ?: return null

            if (manifest.apiVersion != PLUGIN_API_VERSION) {
                Timber.w(
                    "DexPluginLoader: plugin %s has API version %d, expected %d -- skipping %s",
                    manifest.id, manifest.apiVersion, PLUGIN_API_VERSION, jarFile.name,
                )
                return null
            }

            if (!VALID_PLUGIN_ID.matches(manifest.id)) {
                Timber.w(
                    "DexPluginLoader: plugin ID '%s' is invalid -- skipping %s",
                    manifest.id, jarFile.name,
                )
                return null
            }

            val factoryClass = classLoader.loadClass(manifest.factoryClass)
            val factory = factoryClass.getConstructor().newInstance() as? PluginFactory
            if (factory == null) {
                Timber.e(
                    "DexPluginLoader: %s does not implement PluginFactory -- skipping %s",
                    manifest.factoryClass, jarFile.name,
                )
                return null
            }

            Timber.d(
                "DexPluginLoader: discovered plugin %s v%s from %s",
                manifest.id, manifest.version, jarFile.name,
            )
            DiscoveredPlugin(factory, manifest, jarFile)
        } catch (e: Exception) {
            Timber.e(e, "DexPluginLoader: failed to load plugin from %s", jarFile.name)
            null
        }
    }

    private fun readManifest(classLoader: ClassLoader, jarFile: File): PluginManifest? {
        val stream = classLoader.getResourceAsStream(PluginManifest.MANIFEST_PATH)
        if (stream == null) {
            Timber.w(
                "DexPluginLoader: no %s in %s -- skipping",
                PluginManifest.MANIFEST_PATH, jarFile.name,
            )
            return null
        }

        val json = stream.use { s ->
            val reader = s.bufferedReader()
            val buffer = CharArray(MAX_MANIFEST_SIZE)
            val len = reader.read(buffer)
            if (len < 0) {
                ""
            } else {
                // Check if there's more data beyond the limit
                if (reader.read() != -1) {
                    Timber.w(
                        "DexPluginLoader: manifest in %s exceeds %d bytes -- skipping",
                        jarFile.name, MAX_MANIFEST_SIZE,
                    )
                    return null
                }
                String(buffer, 0, len)
            }
        }
        return try {
            PluginManifest.parse(json)
        } catch (e: IllegalArgumentException) {
            Timber.e(e, "DexPluginLoader: invalid manifest in %s", jarFile.name)
            null
        }
    }

    companion object {
        const val PLUGINS_DIR_NAME = "plugins"
        private const val DEX_OUTPUT_DIR_NAME = "plugin_dex"
        /** Maximum manifest size: 64 KB. Prevents OOM from malicious JARs. */
        private const val MAX_MANIFEST_SIZE = 65_536
        internal val VALID_PLUGIN_ID = Regex("^[a-zA-Z][a-zA-Z0-9._-]{1,127}$")
    }
}
