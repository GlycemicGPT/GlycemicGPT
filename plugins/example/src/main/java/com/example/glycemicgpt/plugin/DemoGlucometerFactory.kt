package com.example.glycemicgpt.plugin

import com.glycemicgpt.mobile.domain.plugin.PLUGIN_API_VERSION
import com.glycemicgpt.mobile.domain.plugin.Plugin
import com.glycemicgpt.mobile.domain.plugin.PluginContext
import com.glycemicgpt.mobile.domain.plugin.PluginFactory
import com.glycemicgpt.mobile.domain.plugin.PluginMetadata

/**
 * Factory for the Demo Glucometer runtime plugin.
 *
 * ## Requirements for runtime plugin factories
 *
 * 1. **No-arg constructor** -- the host app instantiates factories via reflection
 *    from the JAR's DEX bytecode. Factories cannot use dependency injection.
 *
 * 2. **metadata** -- must be available before [create] is called. The platform
 *    uses this to display plugin info in the Settings UI (name, version, etc.)
 *    and to check API version compatibility.
 *
 * 3. **create()** -- returns a new [Plugin] instance. Called once per plugin
 *    lifecycle. The [PluginContext] is passed to the plugin's initialize()
 *    method by the platform, NOT to the factory.
 *
 * ## Compile-time vs runtime factories
 *
 * - **Compile-time** (e.g., TandemPluginFactory): Uses `@Inject` constructor,
 *   registered via Hilt `@IntoSet` multibinding. Can inject dependencies.
 * - **Runtime** (this class): Uses no-arg constructor, discovered via
 *   `META-INF/plugin.json` manifest. Cannot inject dependencies.
 */
class DemoGlucometerFactory : PluginFactory {

    override val metadata = PluginMetadata(
        id = DemoGlucometerPlugin.PLUGIN_ID,
        name = "Demo Glucometer",
        version = "1.0.0",
        apiVersion = PLUGIN_API_VERSION,
        description = "Comprehensive plugin showcase simulating a Bluetooth glucose meter. " +
            "Demonstrates dashboard cards, settings UI, event bus, safety limits, " +
            "BGM readings, and data sync.",
        author = "GlycemicGPT",
    )

    override fun create(context: PluginContext): Plugin {
        // For runtime plugins, the factory simply creates a new instance.
        // The platform calls plugin.initialize(context) separately.
        return DemoGlucometerPlugin()
    }
}
