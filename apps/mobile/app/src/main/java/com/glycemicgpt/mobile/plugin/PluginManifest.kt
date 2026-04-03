package com.glycemicgpt.mobile.plugin

import org.json.JSONException
import org.json.JSONObject

/**
 * Parsed contents of `META-INF/plugin.json` inside a runtime plugin JAR.
 *
 * Every runtime plugin JAR must contain this manifest at the resource path
 * `META-INF/plugin.json`. The manifest declares the plugin's identity,
 * compatibility, and entry-point class.
 */
data class PluginManifest(
    /** Fully-qualified class name of the [PluginFactory] implementation. */
    val factoryClass: String,
    /** Must match [PLUGIN_API_VERSION] in the host app. */
    val apiVersion: Int,
    /** Reverse-domain plugin ID (e.g. "com.example.my-plugin"). */
    val id: String,
    /** Human-readable display name. */
    val name: String,
    /** Semantic version string (e.g. "1.0.0"). */
    val version: String,
    /** Optional author name. */
    val author: String = "",
    /** Optional short description. */
    val description: String = "",
) {
    companion object {
        /** Resource path where the manifest must reside inside the JAR. */
        const val MANIFEST_PATH = "META-INF/plugin.json"

        /**
         * Parse manifest JSON from a string.
         * @throws IllegalArgumentException if required fields are missing or invalid
         */
        fun parse(json: String): PluginManifest {
            val obj = try {
                JSONObject(json)
            } catch (e: JSONException) {
                throw IllegalArgumentException("Invalid plugin manifest JSON", e)
            }

            val factoryClass = obj.optString("factoryClass", "").ifBlank {
                throw IllegalArgumentException("Manifest missing required field: factoryClass")
            }
            val id = obj.optString("id", "").ifBlank {
                throw IllegalArgumentException("Manifest missing required field: id")
            }
            val name = obj.optString("name", "").ifBlank {
                throw IllegalArgumentException("Manifest missing required field: name")
            }
            val version = obj.optString("version", "").ifBlank {
                throw IllegalArgumentException("Manifest missing required field: version")
            }
            val apiVersion = try {
                obj.getInt("apiVersion")
            } catch (e: JSONException) {
                throw IllegalArgumentException("Manifest missing or invalid required field: apiVersion", e)
            }
            if (apiVersion < 1) {
                throw IllegalArgumentException("Manifest apiVersion must be >= 1, got: $apiVersion")
            }

            return PluginManifest(
                factoryClass = factoryClass,
                apiVersion = apiVersion,
                id = id,
                name = name,
                version = version,
                author = obj.optString("author", ""),
                description = obj.optString("description", ""),
            )
        }

        // Callers use PluginManifest.MANIFEST_PATH directly.
    }
}
