package com.example.glycemicgpt.plugin

import com.glycemicgpt.mobile.domain.model.BgmReading
import com.glycemicgpt.mobile.domain.plugin.PLUGIN_API_VERSION
import com.glycemicgpt.mobile.domain.plugin.Plugin
import com.glycemicgpt.mobile.domain.plugin.PluginCapability
import com.glycemicgpt.mobile.domain.plugin.PluginCapabilityInterface
import com.glycemicgpt.mobile.domain.plugin.PluginContext
import com.glycemicgpt.mobile.domain.plugin.PluginMetadata
import com.glycemicgpt.mobile.domain.plugin.capabilities.BgmSource
import com.glycemicgpt.mobile.domain.plugin.events.PluginEvent
import com.glycemicgpt.mobile.domain.plugin.ui.ButtonStyle
import com.glycemicgpt.mobile.domain.plugin.ui.CardElement
import com.glycemicgpt.mobile.domain.plugin.ui.DashboardCardDescriptor
import com.glycemicgpt.mobile.domain.plugin.ui.DropdownOption
import com.glycemicgpt.mobile.domain.plugin.ui.LabelStyle
import com.glycemicgpt.mobile.domain.plugin.ui.PluginIcon
import com.glycemicgpt.mobile.domain.plugin.ui.PluginSettingsDescriptor
import com.glycemicgpt.mobile.domain.plugin.ui.PluginSettingsSection
import com.glycemicgpt.mobile.domain.plugin.ui.SettingDescriptor
import com.glycemicgpt.mobile.domain.plugin.ui.DetailElement
import com.glycemicgpt.mobile.domain.plugin.ui.DetailScreenDescriptor
import com.glycemicgpt.mobile.domain.plugin.ui.UiColor
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.reflect.KClass

/**
 * Comprehensive demo plugin simulating a "Demo Glucometer" -- a fictional
 * Bluetooth blood glucose meter.
 *
 * This plugin serves as the definitive reference implementation for the
 * GlycemicGPT plugin API. It demonstrates every plugin capability:
 *
 * 1. **Lifecycle** -- initialize, shutdown, onActivated, onDeactivated
 * 2. **Dashboard Cards** -- LargeValue, StatusBadge, Row, IconValue, SparkLine, ProgressBar
 * 3. **Settings UI** -- Toggle, Slider, Dropdown, TextInput, ActionButton, InfoText
 * 4. **Event Bus** -- Publishing NewBgmReading events
 * 5. **Safety Limits** -- Validating readings against platform-enforced glucose bounds
 * 6. **Settings Persistence** -- Reading/writing plugin config via PluginSettingsStore
 * 7. **BgmSource Capability** -- Implementing a capability interface
 *
 * ## Why BGM_SOURCE + DATA_SYNC?
 *
 * - BGM_SOURCE is multi-instance (won't conflict with Tandem's GLUCOSE_SOURCE)
 * - DATA_SYNC is multi-instance (won't conflict with anything)
 * - This lets users run the demo alongside real plugins without conflicts
 *
 * ## For plugin authors
 *
 * Read this file top-to-bottom. Every section is commented explaining what
 * each API call does, why it's needed, and what alternatives exist. Use this
 * as your template when building real pump/CGM/BGM drivers.
 */
class DemoGlucometerPlugin : Plugin {

    // -- Metadata --
    // Declared here AND in the factory. The factory's metadata is used before
    // the plugin is instantiated (for the Settings UI list). The plugin's
    // metadata is used after instantiation (for event publishing, logging).

    override val metadata = PluginMetadata(
        id = PLUGIN_ID,
        name = "Demo Glucometer",
        version = "1.0.0",
        apiVersion = PLUGIN_API_VERSION,
        description = "Comprehensive plugin showcase simulating a Bluetooth glucose meter. " +
            "Demonstrates dashboard cards, settings UI, event bus, safety limits, " +
            "BGM readings, and data sync.",
        author = "GlycemicGPT",
    )

    // -- Capabilities --
    // BGM_SOURCE: provides fingerstick readings (multi-instance, no conflicts)
    // DATA_SYNC: syncs data to external services (multi-instance, no conflicts)

    override val capabilities: Set<PluginCapability> = setOf(
        PluginCapability.BGM_SOURCE,
        PluginCapability.DATA_SYNC,
    )

    // -- Internal state --

    @Volatile private var context: PluginContext? = null
    private var scope: CoroutineScope? = null
    @Volatile private var isActive = false
    private val simulator = ReadingSimulator()
    private var bgmSource: DemoBgmSource? = null
    @Volatile private var readingCount = 0
    @Volatile private var lastSyncTime: Instant? = null
    @Volatile private var simulatedBattery = 87f

    // -- Lifecycle --

    /**
     * Called once after the plugin is created by the factory.
     *
     * This is where you store the [PluginContext] reference and set up
     * long-lived resources. Do NOT start heavy operations here -- wait
     * for [onActivated].
     *
     * Available via context:
     * - androidContext: Android Context (restricted for runtime plugins)
     * - settingsStore: Per-plugin key-value persistence
     * - credentialProvider: Per-plugin credential storage (scoped for runtime plugins)
     * - debugLogger: BLE packet logger (useful for device plugins)
     * - eventBus: Cross-plugin event publishing/subscribing
     * - safetyLimits: Read-only StateFlow of current safety limits
     */
    override fun initialize(context: PluginContext) {
        this.context = context
        println("DemoGlucometer: initialized (pluginId=${context.pluginId}, " +
            "apiVersion=${context.apiVersion})")

        // Create the BgmSource capability delegate.
        // The interval comes from settings (default 30 seconds).
        bgmSource = DemoBgmSource(
            simulator = simulator,
            safetyLimits = context.safetyLimits,
            intervalProvider = {
                context.settingsStore.getFloat(KEY_SIM_INTERVAL, DEFAULT_INTERVAL).toLong()
            },
        )
    }

    /**
     * Called when the plugin is being destroyed (app shutdown or plugin removal).
     *
     * Release ALL resources here: cancel coroutines, close BLE connections,
     * unregister callbacks. After this call, the plugin instance is garbage collected.
     */
    override fun shutdown() {
        println("DemoGlucometer: shutdown")
        isActive = false
        scope?.cancel()
        scope = null
        bgmSource = null
        context = null
    }

    /**
     * Called when the user activates this plugin.
     *
     * For device plugins, this is where you'd start auto-reconnect, BLE scanning,
     * or data polling. For this demo, we start the simulated reading generator
     * and begin publishing events.
     */
    override fun onActivated() {
        val ctx = context ?: return
        println("DemoGlucometer: activated -- starting simulation")

        // Load persisted settings
        val simEnabled = ctx.settingsStore.getBoolean(KEY_SIM_ENABLED, true)
        if (!simEnabled) {
            println("DemoGlucometer: simulation disabled in settings, skipping")
            return
        }

        // Create a coroutine scope for background work.
        // SupervisorJob ensures one child failure doesn't cancel others.
        val pluginScope = CoroutineScope(Dispatchers.Default + SupervisorJob())
        scope = pluginScope
        isActive = true

        // Start collecting simulated readings and publishing events
        pluginScope.launch {
            val intervalSec = ctx.settingsStore.getFloat(KEY_SIM_INTERVAL, DEFAULT_INTERVAL).toLong()
            simulator.start(intervalSec, ctx.safetyLimits).collect { reading ->
                readingCount++
                lastSyncTime = Instant.now()
                // Publish a NewBgmReading event on the event bus.
                // Other plugins (e.g., a CGM calibration target) can subscribe
                // to these events for cross-plugin workflows.
                ctx.eventBus.publish(
                    PluginEvent.NewBgmReading(
                        pluginId = metadata.id,
                        reading = reading,
                    ),
                )
                println("DemoGlucometer: published reading #$readingCount: " +
                    "${reading.glucoseMgDl} mg/dL")

                // Simulate battery drain (very slow)
                simulatedBattery = (simulatedBattery - 0.1f).coerceAtLeast(0f)
            }
        }
    }

    /**
     * Called when the user deactivates this plugin (or another plugin replaces it).
     *
     * Stop all operations but do NOT clear stored credentials or settings --
     * the user may reactivate later.
     */
    override fun onDeactivated() {
        println("DemoGlucometer: deactivated -- stopping simulation")
        isActive = false
        scope?.cancel()
        scope = null
    }

    // -- Dashboard Cards --

    /**
     * Provides dashboard cards that the platform renders on the home screen.
     *
     * Returns a Flow so cards can update reactively. For this demo we use a
     * polling flow that refreshes every 5 seconds. Real plugins would typically
     * use a StateFlow or combine multiple data sources.
     *
     * Cards are rendered in priority order (lower = higher on screen).
     * The platform's core cards (GlucoseHero, TrendChart, TimeInRange) have
     * priority 0-50. Plugin cards should use 100+ to appear below them.
     */
    override fun observeDashboardCards(): Flow<List<DashboardCardDescriptor>> = flow {
        while (true) {
            val cards = mutableListOf<DashboardCardDescriptor>()

            // Card 1: Demo Glucometer status
            cards.add(buildGlucometerCard())

            // Card 2: Data Sync status
            cards.add(buildSyncCard())

            emit(cards)
            kotlinx.coroutines.delay(5000L)
        }
    }

    /**
     * Builds the primary glucometer status card.
     * Demonstrates: LargeValue, StatusBadge, Row, IconValue, SparkLine, ProgressBar
     */
    private fun buildGlucometerCard(): DashboardCardDescriptor {
        val latest = simulator.latestReading
        val glucoseValue = latest?.glucoseMgDl?.toString() ?: "--"
        val glucoseColor = when {
            latest == null -> UiColor.MUTED
            latest.glucoseMgDl < 70 -> UiColor.ERROR      // Low
            latest.glucoseMgDl > 180 -> UiColor.WARNING    // High
            else -> UiColor.SUCCESS                         // In range
        }

        val elements = mutableListOf<CardElement>()

        // Large glucose value -- the primary metric
        elements.add(
            CardElement.LargeValue(
                value = glucoseValue,
                unit = "mg/dL",
                color = glucoseColor,
            ),
        )

        // Status badge -- indicates this is simulated data
        elements.add(
            CardElement.StatusBadge(
                text = "Simulated",
                color = UiColor.INFO,
            ),
        )

        // Row with battery and reading count
        elements.add(
            CardElement.Row(
                elements = listOf(
                    CardElement.IconValue(
                        icon = PluginIcon.BATTERY,
                        value = "${simulatedBattery.toInt()}%",
                        label = "Battery",
                    ),
                    CardElement.IconValue(
                        icon = PluginIcon.GLUCOSE,
                        value = "$readingCount",
                        label = "Readings",
                    ),
                ),
            ),
        )

        // SparkLine showing recent reading history
        val sparkData = simulator.history
        if (sparkData.isNotEmpty()) {
            elements.add(
                CardElement.SparkLine(
                    values = sparkData,
                    label = "Recent readings",
                ),
            )
        }

        // Battery progress bar
        elements.add(
            CardElement.ProgressBar(
                value = simulatedBattery,
                max = 100f,
                label = "Battery",
            ),
        )

        return DashboardCardDescriptor(
            id = "demo-glucometer-status",
            title = "Demo Glucometer",
            priority = 100,
            elements = elements,
            hasDetail = true,
        )
    }

    /**
     * Builds the data sync status card.
     * Demonstrates: Label, IconValue, StatusBadge with different states
     */
    private fun buildSyncCard(): DashboardCardDescriptor {
        val syncTime = lastSyncTime
        val syncLabel = if (syncTime != null) {
            val formatter = DateTimeFormatter.ofPattern("HH:mm:ss")
                .withZone(ZoneId.systemDefault())
            "Last sync: ${formatter.format(syncTime)}"
        } else {
            "No data synced yet"
        }

        return DashboardCardDescriptor(
            id = "demo-glucometer-sync",
            title = "Data Sync Status",
            priority = 110,
            elements = listOf(
                CardElement.Label(
                    text = syncLabel,
                    style = LabelStyle.CAPTION,
                ),
                CardElement.IconValue(
                    icon = PluginIcon.SYNC,
                    value = "$readingCount",
                    label = "Records synced",
                ),
                CardElement.StatusBadge(
                    text = if (isActive) "Connected" else "Disconnected",
                    color = if (isActive) UiColor.SUCCESS else UiColor.MUTED,
                ),
            ),
        )
    }

    // -- Settings UI --

    /**
     * Declares the plugin's settings UI as a descriptor.
     *
     * The platform renders these descriptors using Material 3 components in
     * Settings > Plugins > [Plugin Name]. Each setting type maps to a specific
     * UI component. The platform handles reading/writing values to the
     * PluginSettingsStore automatically for Toggle, Slider, Dropdown, and TextInput.
     *
     * ActionButtons trigger callbacks that the platform routes back to the plugin
     * (via the settings store -- the platform writes a timestamp to the button's key).
     */
    override fun settingsDescriptor(): PluginSettingsDescriptor = PluginSettingsDescriptor(
        sections = listOf(
            // Section 1: Simulation settings
            PluginSettingsSection(
                title = "Simulation Settings",
                items = listOf(
                    // Toggle: on/off switch. The platform reads/writes a Boolean
                    // via settingsStore.getBoolean(key) / putBoolean(key, value).
                    SettingDescriptor.Toggle(
                        key = KEY_SIM_ENABLED,
                        label = "Enable Simulation",
                        description = "Generate simulated glucose readings at the configured interval",
                    ),
                    // Slider: numeric range selector. The platform reads/writes a Float
                    // via settingsStore.getFloat(key) / putFloat(key, value).
                    SettingDescriptor.Slider(
                        key = KEY_SIM_INTERVAL,
                        label = "Reading Interval (seconds)",
                        min = 5f,
                        max = 300f,
                        step = 5f,
                        unit = "sec",
                    ),
                    // Dropdown: selection from predefined options. The platform writes
                    // the selected option's value via settingsStore.putString(key, value).
                    SettingDescriptor.Dropdown(
                        key = KEY_GLUCOSE_UNIT,
                        label = "Glucose Unit",
                        options = listOf(
                            DropdownOption(value = "mg_dl", label = "mg/dL"),
                            DropdownOption(value = "mmol_l", label = "mmol/L"),
                        ),
                    ),
                ),
            ),

            // Section 2: Data sync settings
            PluginSettingsSection(
                title = "Data Sync",
                items = listOf(
                    // TextInput: free-form text field. The platform reads/writes a String
                    // via settingsStore.getString(key) / putString(key, value).
                    // Set sensitive=true to mask input (for API keys, passwords).
                    SettingDescriptor.TextInput(
                        key = KEY_SYNC_URL,
                        label = "Sync Endpoint URL",
                        hint = "https://your-nightscout-instance.com/api/v1",
                    ),
                    SettingDescriptor.Toggle(
                        key = KEY_AUTO_SYNC,
                        label = "Auto-sync",
                        description = "Automatically upload readings to the sync endpoint",
                    ),
                    // ActionButton (PRIMARY): triggers an action. The platform writes
                    // a timestamp to the key when clicked. The plugin can observe
                    // changes to react. Style options: DEFAULT, PRIMARY, DESTRUCTIVE.
                    SettingDescriptor.ActionButton(
                        key = KEY_SYNC_NOW,
                        label = "Sync Now",
                        style = ButtonStyle.PRIMARY,
                    ),
                    // ActionButton (DESTRUCTIVE): red button for dangerous operations.
                    // The platform should show a confirmation dialog before executing.
                    SettingDescriptor.ActionButton(
                        key = KEY_CLEAR_DATA,
                        label = "Clear Local Data",
                        style = ButtonStyle.DESTRUCTIVE,
                    ),
                ),
            ),

            // Section 3: About
            PluginSettingsSection(
                title = "About",
                items = listOf(
                    // InfoText: read-only display text. Use for version info,
                    // descriptions, legal notices, or help text.
                    SettingDescriptor.InfoText(
                        key = "about_info",
                        text = "Demo Glucometer v1.0.0 | Plugin API v$PLUGIN_API_VERSION\n\n" +
                            "This plugin simulates a Bluetooth glucose meter to demonstrate " +
                            "the full GlycemicGPT plugin API. It is not a real medical device.",
                    ),
                    SettingDescriptor.InfoText(
                        key = "safety_info",
                        text = buildSafetyInfoText(),
                    ),
                ),
            ),
        ),
    )

    // -- Detail Screen --

    /**
     * Provides a rich detail view for the glucometer status card.
     * Includes reading history, manual entry, simulator controls, and safety info.
     */
    override fun observeDetailScreen(cardId: String): Flow<DetailScreenDescriptor>? {
        if (cardId != "demo-glucometer-status") return null

        return flow {
            while (true) {
                emit(buildDetailScreen())
                kotlinx.coroutines.delay(3000L)
            }
        }
    }

    override fun onDetailAction(cardId: String, actionKey: String) {
        if (cardId != "demo-glucometer-status") return
        val ctx = context ?: return

        when (actionKey) {
            KEY_DETAIL_RECORD -> {
                val valueStr = ctx.settingsStore.getString(KEY_DETAIL_BG_VALUE, "")
                val value = valueStr.toIntOrNull()
                if (value != null && value in 20..500) {
                    // Add to simulator history and publish event
                    simulator.addManualReading(value.toFloat())
                    readingCount++
                    lastSyncTime = Instant.now()
                    ctx.eventBus.publish(
                        PluginEvent.NewBgmReading(
                            pluginId = metadata.id,
                            reading = BgmReading(
                                glucoseMgDl = value,
                                timestamp = Instant.now(),
                                meterName = "Demo Glucometer (manual)",
                            ),
                        ),
                    )
                    println("DemoGlucometer: manual reading recorded: $value mg/dL")
                    // Clear the input field
                    ctx.settingsStore.putString(KEY_DETAIL_BG_VALUE, "")
                } else {
                    println("DemoGlucometer: invalid manual reading value: $valueStr")
                }
            }
        }
    }

    private fun buildDetailScreen(): DetailScreenDescriptor {
        val elements = mutableListOf<DetailElement>()

        // Section: Recent Readings
        elements.add(DetailElement.SectionHeader("Recent Readings"))
        val history = simulator.recentReadings
        if (history.isEmpty()) {
            elements.add(
                DetailElement.Display(
                    CardElement.Label(
                        text = "No readings yet. Activate the simulator or enter a manual reading.",
                        style = LabelStyle.CAPTION,
                    ),
                ),
            )
        } else {
            val formatter = DateTimeFormatter.ofPattern("HH:mm:ss")
                .withZone(ZoneId.systemDefault())
            history.takeLast(10).reversed().forEach { (timestamp, glucose) ->
                elements.add(
                    DetailElement.Display(
                        CardElement.Label(
                            text = "${formatter.format(timestamp)}  -  ${glucose.toInt()} mg/dL",
                            style = LabelStyle.BODY,
                        ),
                    ),
                )
            }
        }

        // SparkLine of recent values
        val sparkData = simulator.history
        if (sparkData.size >= 2) {
            elements.add(
                DetailElement.Display(
                    CardElement.SparkLine(
                        values = sparkData,
                        label = "Glucose trend",
                    ),
                ),
            )
        }

        // Section: Manual Entry
        elements.add(DetailElement.SectionHeader("Manual Entry"))
        elements.add(
            DetailElement.Interactive(
                SettingDescriptor.TextInput(
                    key = KEY_DETAIL_BG_VALUE,
                    label = "Blood Glucose (mg/dL)",
                    hint = "Enter value between 20-500",
                ),
            ),
        )
        elements.add(
            DetailElement.Interactive(
                SettingDescriptor.ActionButton(
                    key = KEY_DETAIL_RECORD,
                    label = "Record Reading",
                    style = ButtonStyle.PRIMARY,
                ),
            ),
        )

        // Section: Simulator Controls
        elements.add(DetailElement.SectionHeader("Simulator Controls"))
        elements.add(
            DetailElement.Interactive(
                SettingDescriptor.Toggle(
                    key = KEY_SIM_ENABLED,
                    label = "Enable Simulation",
                    description = "Generate simulated glucose readings automatically",
                ),
            ),
        )
        elements.add(
            DetailElement.Interactive(
                SettingDescriptor.Slider(
                    key = KEY_SIM_INTERVAL,
                    label = "Reading Interval",
                    min = 5f,
                    max = 300f,
                    step = 5f,
                    unit = "sec",
                ),
            ),
        )

        // Section: Safety Info
        elements.add(DetailElement.SectionHeader("Safety Info"))
        elements.add(
            DetailElement.Display(
                CardElement.Label(
                    text = buildSafetyInfoText(),
                    style = LabelStyle.CAPTION,
                ),
            ),
        )

        return DetailScreenDescriptor(
            title = "Demo Glucometer",
            elements = elements,
        )
    }

    // -- Capability Interface --

    /**
     * Returns capability implementations for the declared capabilities.
     *
     * The platform calls this to get typed access to the plugin's capabilities.
     * For each capability declared in [capabilities], return the corresponding
     * interface implementation. Return null for unknown types.
     *
     * Common pattern: create capability delegates in [initialize] and return
     * them here. This keeps the main plugin class focused on lifecycle/settings
     * while the capability logic lives in dedicated classes.
     */
    @Suppress("UNCHECKED_CAST")
    override fun <T : PluginCapabilityInterface> getCapability(type: KClass<T>): T? =
        when (type) {
            BgmSource::class -> bgmSource as? T
            // DATA_SYNC has no interface yet (reserved for future use),
            // so we don't return anything for it.
            else -> null
        }

    /**
     * Builds the safety info text for the settings descriptor.
     * Reads current safety limits if available; falls back to a generic message
     * after shutdown when the context is null.
     */
    private fun buildSafetyInfoText(): String {
        val limits = context?.safetyLimits?.value
        return if (limits != null) {
            "Safety: All readings are validated against platform safety limits " +
                "(${limits.minGlucoseMgDl}-${limits.maxGlucoseMgDl} mg/dL). " +
                "Out-of-range values are automatically dropped."
        } else {
            "Safety: All readings are validated against platform safety limits. " +
                "Out-of-range values are automatically dropped."
        }
    }

    companion object {
        const val PLUGIN_ID = "com.example.glycemicgpt.demo-glucometer"

        // Settings keys -- must match ^[a-zA-Z][a-zA-Z0-9_.-]{0,127}$
        private const val KEY_SIM_ENABLED = "sim_enabled"
        private const val KEY_SIM_INTERVAL = "sim_interval"
        private const val KEY_GLUCOSE_UNIT = "glucose_unit"
        private const val KEY_SYNC_URL = "sync_url"
        private const val KEY_AUTO_SYNC = "auto_sync"
        private const val KEY_SYNC_NOW = "sync_now"
        private const val KEY_CLEAR_DATA = "clear_data"

        // Detail screen keys
        private const val KEY_DETAIL_BG_VALUE = "detail_bg_value"
        private const val KEY_DETAIL_RECORD = "detail_record_reading"

        private const val DEFAULT_INTERVAL = 30f
    }
}
