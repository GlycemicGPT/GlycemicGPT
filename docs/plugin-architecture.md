# Plugin Architecture

Developer guide for building GlycemicGPT mobile plugins.

---

## Table of Contents

- [Overview](#overview)
- [Getting Started](#getting-started)
- [Plugin Interfaces](#plugin-interfaces)
- [Capabilities](#capabilities)
- [Declarative UI](#declarative-ui)
- [Event Bus](#event-bus)
- [DI Registration](#di-registration)
- [Safety Invariants](#safety-invariants)
- [Reference Implementation](#reference-implementation)
- [API Versioning](#api-versioning)
- [Runtime Plugin Loading](#runtime-plugin-loading)
- [ProGuard Rules](#proguard-rules)

---

## Overview

GlycemicGPT's mobile app uses a three-layer plugin architecture:

```
+---------------------------------------------------+
|                  Platform (:app)                   |
|  PluginRegistry, UI renderers, safety enforcement  |
+---------------------------------------------------+
|              Plugin API (:pump-driver-api)          |
|  Plugin, DevicePlugin, capabilities, event bus,    |
|  declarative UI types, domain models               |
+---------------------------------------------------+
|                    Plugins                          |
|  plugins/shipped/tandem, future: omnipod, etc      |
+---------------------------------------------------+
```

**Platform** (`:app` module) -- Owns the `PluginRegistry`, core UI (GlucoseHero, TrendChart, TimeInRange), safety limit enforcement, and plugin lifecycle management. Plugins never import from this module.

**Plugin API** (`:pump-driver-api` module, at `plugins/pump-driver-api/`) -- Defines all interfaces, capability contracts, event types, declarative UI descriptors, and domain models. Both the platform and plugins depend on this module.

**Plugins** (e.g., `:tandem-pump-driver` at `plugins/shipped/tandem/`) -- Implement one or more capability interfaces. Each shipped plugin is a separate Gradle module under `plugins/shipped/` that depends only on `:pump-driver-api`. Discovered at compile time via Hilt multibindings.

### Design Principles

- **Capability-based**: Plugins declare what they can do (`GLUCOSE_SOURCE`, `INSULIN_SOURCE`, etc.), not what they are. The platform routes data and enforces mutual exclusion based on capabilities.
- **Safety-first**: Safety limits are owned by the platform, synced from the backend, and passed to plugins as read-only constraints. Plugins cannot override or bypass them.
- **Dual discovery**: Compile-time plugins are discovered via Hilt `@IntoSet` multibindings. Runtime plugins are loaded from sideloaded JAR files via `DexClassLoader`.
- **Declarative UI**: Plugins describe their settings and dashboard cards using descriptor types. The platform renders them using Material 3 components.

---

## Getting Started

### Gradle Module Setup

Create a new Gradle module under `plugins/shipped/`:

```
plugins/shipped/
  your-plugin/
    build.gradle.kts
    src/main/kotlin/com/glycemicgpt/mobile/plugin/...
```

Your `build.gradle.kts` should depend on `:pump-driver-api`:

```kotlin
plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
    id("com.google.dagger.hilt.android")
    id("com.google.devtools.ksp")
}

dependencies {
    implementation(project(":pump-driver-api"))

    // Use versions from the project's version catalog (libs.versions.toml)
    // or match the versions used in plugins/shipped/tandem/build.gradle.kts
    implementation(libs.hilt.android)
    ksp(libs.hilt.compiler)
    implementation(libs.kotlinx.coroutines.core)
    implementation(libs.kotlinx.coroutines.android)
}
```

> **Note:** Always reference the project's version catalog (`gradle/libs.versions.toml`) for dependency versions. The `plugins/shipped/tandem/build.gradle.kts` is the canonical example. Do not hardcode version strings.

Then add the module to `apps/mobile/settings.gradle.kts`:

```kotlin
include(":your-plugin")
project(":your-plugin").projectDir = file("../../plugins/shipped/your-plugin")
```

And add it as a dependency in `:app`:

```kotlin
// apps/mobile/app/build.gradle.kts
dependencies {
    implementation(project(":your-plugin"))
}
```

### Minimum Viable Plugin

A plugin needs three things:

1. A class implementing `Plugin` (or `DevicePlugin` for hardware)
2. A `PluginFactory` to create instances
3. A Hilt module binding the factory into the `Set<PluginFactory>`

---

## Plugin Interfaces

### Plugin (base)

All plugins implement the `Plugin` interface:

```kotlin
interface Plugin {
    val metadata: PluginMetadata
    val capabilities: Set<PluginCapability>

    fun initialize(context: PluginContext)
    fun shutdown()
    fun onActivated()
    fun onDeactivated()
    fun settingsDescriptor(): PluginSettingsDescriptor
    fun observeDashboardCards(): Flow<List<DashboardCardDescriptor>>
    fun <T : PluginCapabilityInterface> getCapability(type: KClass<T>): T?
}
```

**Lifecycle methods:**

| Method | When Called | Purpose |
|--------|-----------|---------|
| `initialize(context)` | Once, after creation | Set up resources. `PluginContext` provides Android context, settings store, credential provider, event bus, safety limits. |
| `shutdown()` | When plugin is being destroyed | Release all resources. Disconnect hardware, cancel coroutines. |
| `onActivated()` | User selects this plugin as active | Start operations. For device plugins, this is where auto-reconnect should trigger. |
| `onDeactivated()` | Another plugin replaces this one, or user deactivates | Stop operations. Disconnect hardware, but don't clear stored credentials. |

### DevicePlugin (hardware)

For plugins that connect to physical devices (pumps, CGMs, BGMs):

```kotlin
interface DevicePlugin : Plugin {
    fun observeConnectionState(): StateFlow<ConnectionState>
    fun connect(address: String, config: Map<String, String> = emptyMap())
    fun disconnect()
    fun scan(): Flow<DiscoveredDevice>
}
```

`ConnectionState` values: `DISCONNECTED`, `SCANNING`, `CONNECTING`, `AUTHENTICATING`, `AUTH_FAILED`, `CONNECTED`, `RECONNECTING`.

Connection requirements:
- `connect()` must enforce a reasonable timeout (typically 30 seconds)
- `disconnect()` must be safe to call even if not connected (no-op)
- `scan()` returns a Flow that completes when scanning ends; cancel collection to stop early

### PluginFactory

Each plugin provides a factory for the platform to create instances:

```kotlin
interface PluginFactory {
    val metadata: PluginMetadata
    fun create(context: PluginContext): Plugin
}
```

`metadata` is available before the plugin is instantiated, allowing the platform to display plugin information in the UI without creating plugin instances.

### PluginMetadata

```kotlin
data class PluginMetadata(
    val id: String,           // Reverse-domain unique ID, e.g. "com.glycemicgpt.tandem"
    val name: String,         // Human-readable, e.g. "Tandem Insulin Pump"
    val version: String,      // Semantic version, e.g. "1.0.0"
    val apiVersion: Int,      // Must match PLUGIN_API_VERSION
    val description: String,  // Short description
    val author: String,       // Author name
    val iconResName: String?, // Optional drawable resource name
    val protocolName: String?, // BLE/communication protocol family, e.g. "Tandem"
)
```

**Protocol versioning convention:** `protocolName` combined with `version` is displayed as the protocol identifier (e.g., "Tandem v1.0.0"). The plugin `version` field doubles as the protocol version -- bump it when the plugin's BLE protocol handling changes. There is no separate protocol versioning infrastructure.

Plugin IDs must match the pattern `^[a-zA-Z][a-zA-Z0-9._-]{1,127}$` (reverse-domain style).

### PluginContext

Provided by the platform during `initialize()`:

```kotlin
class PluginContext(
    val androidContext: Context,
    val pluginId: String,
    val settingsStore: PluginSettingsStore,
    val credentialProvider: PumpCredentialProvider,
    val debugLogger: DebugLogger,
    val eventBus: PluginEventBus,
    val safetyLimits: StateFlow<SafetyLimits>,
    val apiVersion: Int,
)
```

- **`settingsStore`**: Per-plugin key-value persistence (scoped to plugin ID). For general settings only -- use `credentialProvider` for sensitive credentials.
- **`credentialProvider`**: Encrypted storage for pairing credentials and session data.
- **`safetyLimits`**: Read-only `StateFlow` of current safety limits. Updated by the platform when backend settings change.
- **`eventBus`**: Cross-plugin communication channel.

**Security note**: `androidContext` exposes the full application `Context`. This is acceptable for compile-time plugins in the monorepo but must be replaced with a restricted interface before any runtime-loaded (third-party) plugin support is introduced.

### Settings Store Behavior

`PluginSettingsStore` provides immediate, synchronous persistence (backed by `SharedPreferences`). Key behaviors:

- **Writes are immediate** -- `putString()`, `putBoolean()`, etc. persist synchronously.
- **Data survives deactivation** -- settings are preserved when a plugin is deactivated and restored when reactivated.
- **Data survives app updates** -- settings persist across APK upgrades.
- **Data is scoped by plugin ID** -- each plugin has its own isolated namespace.
- **Uninstall clears all data** -- Android clears SharedPreferences when the app is uninstalled.

For sensitive credentials (pairing codes, session tokens), use `credentialProvider` instead, which uses `EncryptedSharedPreferences`.

### Threading Contract

Plugin lifecycle methods (`initialize`, `shutdown`, `onActivated`, `onDeactivated`) are called on the main thread by `PluginRegistry`. The registry serializes activation/deactivation calls via an internal lock, so these methods will not be called concurrently for the same plugin. However:

- Capability methods (`getIoB()`, `observeReadings()`, etc.) may be called from background coroutine dispatchers.
- `observeDashboardCards()` and `settingsDescriptor()` may be called from the UI thread.
- If your plugin maintains mutable state accessed by both lifecycle and capability methods, use appropriate synchronization.

### Error Handling

If a lifecycle method throws an exception:

- **`initialize()` throws**: Plugin is skipped entirely -- it will not appear in the available plugins list. An error is logged.
- **`onActivated()` throws**: Activation fails and the plugin remains inactive. An error is logged and `Result.failure` is returned to the caller.
- **`onDeactivated()` throws**: The exception is caught and logged, but deactivation continues -- the plugin is removed from the active set regardless.
- **`shutdown()` throws**: Not currently called by the registry (plugins are garbage collected). Future versions may add explicit shutdown.

---

## Capabilities

Plugins declare their capabilities as a `Set<PluginCapability>`. The platform uses these to enforce mutual exclusion and route data.

### Capability Table

| Capability | Interface | Cardinality | Description |
|-----------|-----------|-------------|-------------|
| `GLUCOSE_SOURCE` | `GlucoseSource` | Max 1 active | CGM/glucose readings (CGMs, pumps with CGM stream) |
| `INSULIN_SOURCE` | `InsulinSource` | Max 1 active | IoB, basal rate, bolus history (read-only) |
| `PUMP_STATUS` | `PumpStatus` | Max 1 active | Battery, reservoir, hardware info, history logs (read-only) |
| `PUMP_CONTROL` | *(deferred)* | Max 1 active | Insulin delivery (future, build-from-source only) |
| `BGM_SOURCE` | `BgmSource` | Multiple allowed | Fingerstick blood glucose readings |
| `CALIBRATION_TARGET` | `CalibrationTarget` | Max 1 active | Accepts calibration from BGM readings |
| `DATA_SYNC` | *(not yet defined)* | Multiple allowed | Syncs data to external services (Nightscout, Tidepool). No capability interface exists yet -- this capability is reserved for future use and is not currently implementable. |

**Mutual exclusion**: For single-instance capabilities, activating a new plugin automatically deactivates the previous one for that capability. The platform activates the new plugin first (so the slot is never empty), then deactivates the old one.

### Implementing Capability Interfaces

Return capability instances from `getCapability()`:

```kotlin
override fun <T : PluginCapabilityInterface> getCapability(type: KClass<T>): T? =
    when (type) {
        GlucoseSource::class -> myGlucoseSource as? T
        InsulinSource::class -> myInsulinSource as? T
        else -> null
    }
```

Convenience extension functions are provided for common access patterns:

```kotlin
val glucose: GlucoseSource? = plugin.asGlucoseSource()
val insulin: InsulinSource? = plugin.asInsulinSource()
val pump: PumpStatus? = plugin.asPumpStatus()
val bgm: BgmSource? = plugin.asBgmSource()
val cal: CalibrationTarget? = plugin.asCalibrationTarget()
```

### GlucoseSource

```kotlin
interface GlucoseSource : PluginCapabilityInterface {
    fun observeReadings(): Flow<CgmReading>
    suspend fun getCurrentReading(): Result<CgmReading>
}
```

`CgmReading` values are validated: `glucoseMgDl` must be in 20..500.

### InsulinSource

```kotlin
interface InsulinSource : PluginCapabilityInterface {
    suspend fun getIoB(): Result<IoBReading>
    suspend fun getBasalRate(): Result<BasalReading>
    suspend fun getBolusHistory(since: Instant, limits: SafetyLimits): Result<List<BolusEvent>>
}
```

`getBolusHistory()` receives `SafetyLimits`. **Convention:** implementations should reject bolus events whose dose exceeds `limits.maxBolusDoseMilliunits`. This is not enforced by the interface itself but is a required safety contract -- the platform and existing tests expect out-of-range values to be dropped, not returned.

### PumpStatus

```kotlin
interface PumpStatus : PluginCapabilityInterface {
    suspend fun getBatteryStatus(): Result<BatteryStatus>
    suspend fun getReservoirLevel(): Result<ReservoirReading>
    suspend fun getPumpSettings(): Result<PumpSettings>
    suspend fun getPumpHardwareInfo(): Result<PumpHardwareInfo>
    suspend fun getHistoryLogs(sinceSequence: Int): Result<List<HistoryLogRecord>>
    fun extractCgmFromHistoryLogs(records: List<HistoryLogRecord>, limits: SafetyLimits): List<CgmReading>
    fun extractBolusesFromHistoryLogs(records: List<HistoryLogRecord>, limits: SafetyLimits): List<BolusEvent>
    fun extractBasalFromHistoryLogs(records: List<HistoryLogRecord>, limits: SafetyLimits): List<BasalReading>
    fun unpair()
    fun autoReconnectIfPaired()
}
```

All `extract*` methods receive `SafetyLimits` and must drop out-of-range values (never clamp).

### BgmSource

```kotlin
interface BgmSource : PluginCapabilityInterface {
    fun observeReadings(): Flow<BgmReading>
    suspend fun getLatestReading(): Result<BgmReading>
}
```

### CalibrationTarget

```kotlin
interface CalibrationTarget : PluginCapabilityInterface {
    suspend fun calibrate(bgValueMgDl: Int, timestamp: Instant): Result<Unit>
    suspend fun getCalibrationStatus(): Result<CalibrationStatus>
}
```

The platform validates `bgValueMgDl` against absolute glucose bounds (20..500) before forwarding. Plugins may enforce tighter device-specific limits.

---

## Declarative UI

Plugins describe their UI using descriptor types. The platform renders them.

### Settings Descriptors

`PluginSettingsDescriptor` contains sections, each with a list of `SettingDescriptor` items:

```kotlin
PluginSettingsDescriptor(
    sections = listOf(
        PluginSettingsSection(
            title = "Connection",
            items = listOf(
                SettingDescriptor.InfoText(key = "status", text = "Connected"),
                SettingDescriptor.ActionButton(key = "unpair", label = "Unpair", style = ButtonStyle.DESTRUCTIVE),
            ),
        ),
    ),
)
```

Available setting types:

| Type | Purpose | Key Properties |
|------|---------|----------------|
| `TextInput` | Text field | `label`, `hint`, `sensitive` (masks input) |
| `Toggle` | On/off switch | `label`, `description` |
| `Slider` | Numeric range | `label`, `min`, `max`, `step`, `unit` |
| `Dropdown` | Selection from options | `label`, `options: List<DropdownOption>` |
| `ActionButton` | Clickable button | `label`, `style` (DEFAULT, PRIMARY, DESTRUCTIVE) |
| `InfoText` | Read-only display | `text` |

Setting keys must match `^[a-zA-Z][a-zA-Z0-9_.-]{0,127}$` and be unique within a descriptor.

### Dashboard Card Descriptors

Plugins contribute dashboard cards via `observeDashboardCards()`:

```kotlin
override fun observeDashboardCards(): Flow<List<DashboardCardDescriptor>> = flow {
    emit(listOf(
        DashboardCardDescriptor(
            id = "my-card",
            title = "My Plugin Status",
            priority = 100,  // Lower = higher on dashboard
            elements = listOf(
                CardElement.LargeValue(value = "120", unit = "mg/dL", color = UiColor.SUCCESS),
                CardElement.Label(text = "Last reading 2 min ago", style = LabelStyle.CAPTION),
            ),
        ),
    ))
}
```

Available card elements:

| Element | Purpose |
|---------|---------|
| `LargeValue` | Primary metric display with optional unit and color |
| `Label` | Text with style (TITLE, SUBTITLE, BODY, CAPTION) |
| `StatusBadge` | Colored status indicator |
| `ProgressBar` | Progress indicator with label |
| `IconValue` | Icon + value + label |
| `SparkLine` | Mini line chart from a list of floats |
| `Row` | Horizontal layout container |
| `Column` | Vertical layout container |
| `Spacer` | Vertical spacing (configurable height) |

Colors: `DEFAULT`, `SUCCESS`, `WARNING`, `ERROR`, `INFO`, `MUTED`.

Icons: `BLUETOOTH`, `BATTERY`, `RESERVOIR`, `INSULIN`, `GLUCOSE`, `HEART_RATE`, `SYNC`, `WARNING`, `CHECK`, `CLOCK`, `SETTINGS`, `SIGNAL`, `THERMOMETER`.

---

## Event Bus

The `PluginEventBus` enables cross-plugin communication without direct coupling.

### Publishing Events

```kotlin
// Inside your plugin (context is the PluginContext from initialize())
context.eventBus.publish(
    PluginEvent.NewBgmReading(
        pluginId = metadata.id,
        reading = bgmReading,
    )
)
```

### Subscribing to Events

```kotlin
// Using reified type parameter
context.eventBus.subscribe<PluginEvent.NewBgmReading>()
    .collect { event ->
        // Handle BGM reading from another plugin
    }
```

### Event Types

| Event | Published By | Purpose |
|-------|-------------|---------|
| `NewGlucoseReading` | Glucose source plugins | New CGM reading available |
| `NewBgmReading` | BGM source plugins | New fingerstick reading available |
| `InsulinDelivered` | Insulin source plugins | Bolus delivery event |
| `DeviceConnected` | Device plugins | Hardware connected |
| `DeviceDisconnected` | Device plugins | Hardware disconnected |
| `CalibrationRequested` | BGM plugins | Requesting CGM calibration (value validated: 20..500) |
| `CalibrationCompleted` | Calibration target plugins | Calibration result |
| `SafetyLimitsChanged` | **Platform only** | Safety limits updated from backend |

### Platform-Only Events

`SafetyLimitsChanged` can only be published by the platform. If a plugin attempts to publish a platform-only event, the event bus rejects it. Plugins should observe safety limits via `PluginContext.safetyLimits` (a `StateFlow<SafetyLimits>`) rather than subscribing to this event.

### Calibration Flow Example

A typical BGM-to-CGM calibration flow:

1. BGM plugin receives fingerstick reading from meter
2. BGM plugin publishes `NewBgmReading` event
3. BGM plugin publishes `CalibrationRequested` with the BG value
4. CGM plugin (subscribed to `CalibrationRequested`) sends calibration to the CGM device
5. CGM plugin publishes `CalibrationCompleted` with success/failure
6. BGM plugin (subscribed to `CalibrationCompleted`) updates its UI

---

## DI Registration

Plugins are discovered via Hilt `@IntoSet` multibindings. Each plugin module provides a Hilt module that binds its factory:

```kotlin
@Module
@InstallIn(SingletonComponent::class)
abstract class MyPumpModule {

    @Binds
    @IntoSet
    abstract fun bindMyFactory(impl: MyPluginFactory): PluginFactory
}
```

The factory class uses `@Inject` and `@Singleton`:

```kotlin
@Singleton
class MyPluginFactory @Inject constructor(
    private val myDriver: MyDriver,
    // ... other dependencies
) : PluginFactory {

    override val metadata = PluginMetadata(
        id = "com.glycemicgpt.my-device",
        name = "My Device",
        version = "1.0.0",
        apiVersion = PLUGIN_API_VERSION,
        description = "My custom device plugin",
        author = "My Name",
    )

    override fun create(context: PluginContext): Plugin {
        return MyDevicePlugin(myDriver)
    }
}
```

The platform's `PluginRegistry` receives `Set<PluginFactory>` via constructor injection and creates all plugins at startup.

---

## Safety Invariants

### Platform-Enforced Limits

Safety limits are defined by `SafetyLimits` with absolute bounds that cannot be bypassed:

| Field | Absolute Bound | Default | Source |
|-------|---------------|---------|--------|
| `minGlucoseMgDl` | 20 | 20 | CGM sensor floor |
| `maxGlucoseMgDl` | 500 | 500 | CGM sensor ceiling |
| `maxBasalRateMilliunits` | 15,000 (15 u/hr) | 15,000 | Current hardware max (Tandem) |
| `maxBolusDoseMilliunits` | 25,000 (25 u) | 25,000 | Current hardware max (Tandem) |

> **Note:** The absolute bounds are currently based on Tandem hardware limits (shared across t:slim X2 and Mobi). Future plugins for other pump hardware (OmniPod, Medtronic) may require revisiting these constants if those devices have different physical limits.

User-configured limits (from the backend) narrow these ranges but can never widen them. The `SafetyLimits.safeOf()` factory clamps values to absolute bounds instead of throwing.

### Plugin Responsibilities

- **Read `safetyLimits` from `PluginContext`**: These are the current limits, updated by the platform.
- **Drop out-of-range values**: When extracting data (CGM readings, bolus events, basal rates), drop values outside the limits. Never clamp.
- **Pass limits to extraction methods**: `extractCgmFromHistoryLogs()`, `extractBolusesFromHistoryLogs()`, and `extractBasalFromHistoryLogs()` all receive `SafetyLimits` as a parameter.
- **Do not publish `SafetyLimitsChanged`**: This is a platform-only event.

### PUMP_CONTROL Capability

The `PUMP_CONTROL` capability is defined in the enum but **deferred** -- no control features exist in the app. Pump control plugins are handled differently from monitoring plugins:

- **Never compiled by CI/CD** -- pump control source code lives in the repo as reference implementations only, not as Gradle modules
- **Never shipped in pre-built APKs** -- no GitHub Release artifact will ever contain a pump control plugin
- **User-built only** -- end users who want pump control must compile the plugin themselves and load it via the app's custom plugin loader. By doing so, they accept manufacturer responsibility (see [MEDICAL-DISCLAIMER.md](../MEDICAL-DISCLAIMER.md))
- Must use platform `SafetyLimits` (max bolus, max basal, glucose range) -- these cannot be bypassed
- Must require explicit user confirmation with biometric authentication for every delivery command

See [CONTRIBUTING.md](../CONTRIBUTING.md#device-control-plugins) for the full contribution model.

---

## Reference Implementation

The Tandem plugin (`:tandem-pump-driver`) serves as the reference implementation for shipped plugins.

### Module Structure

```
plugins/shipped/tandem/
  src/main/kotlin/com/glycemicgpt/mobile/
    plugin/
      TandemDevicePlugin.kt      # Main plugin class
      TandemPluginFactory.kt     # Factory for Hilt registration
      TandemGlucoseSource.kt     # GLUCOSE_SOURCE capability
      TandemInsulinSource.kt     # INSULIN_SOURCE capability
      TandemPumpStatus.kt        # PUMP_STATUS capability
    di/
      TandemPumpModule.kt        # Hilt @IntoSet binding
```

### TandemDevicePlugin

The main plugin class implements `DevicePlugin` and declares three capabilities:

```kotlin
class TandemDevicePlugin(
    private val connectionManager: BleConnectionManager,
    private val bleDriver: TandemBleDriver,
    private val scanner: BleScanner,
    private val historyParser: TandemHistoryLogParser,
) : DevicePlugin {

    override val capabilities = setOf(
        PluginCapability.GLUCOSE_SOURCE,
        PluginCapability.INSULIN_SOURCE,
        PluginCapability.PUMP_STATUS,
    )

    // Capability delegates -- thin wrappers around BLE components
    private val glucoseSource = TandemGlucoseSource(bleDriver)
    private val insulinSource = TandemInsulinSource(bleDriver)
    private val pumpStatus = TandemPumpStatus(bleDriver, historyParser, connectionManager)

    override fun <T : PluginCapabilityInterface> getCapability(type: KClass<T>): T? =
        when (type) {
            GlucoseSource::class -> glucoseSource as? T
            InsulinSource::class -> insulinSource as? T
            PumpStatus::class -> pumpStatus as? T
            else -> null
        }
    // ...
}
```

### Capability Delegates

Each capability is a thin wrapper that delegates to the existing BLE components:

```kotlin
class TandemGlucoseSource(
    private val bleDriver: TandemBleDriver,
) : GlucoseSource {
    override fun observeReadings(): Flow<CgmReading> = flow {
        while (true) {
            bleDriver.getCgmStatus().onSuccess { emit(it) }
            delay(60_000L)
        }
    }

    override suspend fun getCurrentReading(): Result<CgmReading> =
        bleDriver.getCgmStatus()
}
```

This pattern keeps plugin code simple: the complexity lives in the BLE layer, and the plugin just adapts it to the capability interface.

### DI Binding

```kotlin
@Module
@InstallIn(SingletonComponent::class)
abstract class TandemPumpModule {

    @Binds
    @IntoSet
    abstract fun bindTandemFactory(impl: TandemPluginFactory): PluginFactory
}
```

---

## API Versioning

### PLUGIN_API_VERSION

The constant `PLUGIN_API_VERSION` (currently `2`) is declared in `PluginMetadata.kt`. Each `PluginMetadata` includes the `apiVersion` the plugin was built against.

### Version Check Behavior

During `PluginRegistry.initialize()`, each factory's `metadata.apiVersion` is checked against the platform's `PLUGIN_API_VERSION`:

- **Match**: Plugin is created and registered normally.
- **Mismatch**: Plugin is **skipped with a warning** log. It does not crash the app.

```
W/PluginRegistry: Plugin com.example.foo has API version 2, expected 1 -- skipping
```

This allows the platform to evolve without breaking older plugins at runtime. Plugins should be recompiled against the new API version when it changes.

### When the Version Changes

Increment `PLUGIN_API_VERSION` when making breaking changes to:
- `Plugin` or `DevicePlugin` interface methods
- Capability interfaces (`GlucoseSource`, `InsulinSource`, etc.)
- `PluginContext` constructor parameters
- `PluginEvent` sealed class variants
- `SettingDescriptor` or `CardElement` sealed class variants

Non-breaking additions (new optional fields, new event types) do not require a version bump.

---

## Runtime Plugin Loading

In addition to compile-time plugins (discovered via Hilt multibindings), GlycemicGPT supports **runtime plugin loading** -- community-developed plugins can be sideloaded as JAR files without recompiling the app.

### How It Works

1. **JAR files** containing DEX bytecode are placed in the app's plugins directory (`files/plugins/`)
2. At startup, `PluginRegistry` scans this directory using `DexPluginLoader`
3. Each JAR is loaded via Android's `DexClassLoader` with the app's ClassLoader as parent (providing `pump-driver-api` classes)
4. The loader reads `META-INF/plugin.json` from the JAR to discover the factory class, plugin ID, and API version
5. The factory is instantiated via reflection (no-arg constructor required)
6. The plugin receives a **restricted** `PluginContext` (see Security below)

Users can also install plugins at runtime via Settings > Plugins > Custom Plugins > Add Plugin.

### Plugin Manifest Format

Every runtime plugin JAR must contain `META-INF/plugin.json`:

```json
{
  "factoryClass": "com.example.MyPluginFactory",
  "apiVersion": 1,
  "id": "com.example.my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "author": "Author Name",
  "description": "Short description"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `factoryClass` | Yes | Fully-qualified class name of the `PluginFactory` implementation |
| `apiVersion` | Yes | Must match the host app's `PLUGIN_API_VERSION` (currently `2`) |
| `id` | Yes | Reverse-domain plugin ID (pattern: `^[a-zA-Z][a-zA-Z0-9._-]{1,127}$`) |
| `name` | Yes | Human-readable display name |
| `version` | Yes | Semantic version string |
| `author` | No | Author name (shown in Settings UI) |
| `description` | No | Short description |

### Security Restrictions

Runtime plugins receive a `RestrictedPluginContext` that blocks app-scope escape vectors while allowing hardware/system access needed for BLE pump and CGM drivers.

**Design philosophy:** Safety enforcement comes from `SafetyLimits` (synced from the backend), not from blanket Context restrictions. Plugins need `getSystemService()` to access hardware services for device communication, but non-hardware services are blocked to prevent data exfiltration.

| Operation | Status | Notes |
|-----------|--------|-------|
| `startActivity()` | Blocked | `SecurityException` -- prevents launching arbitrary UI |
| `startService()` / `startForegroundService()` / `bindService()` | Blocked | `SecurityException` -- prevents starting Android services |
| `sendBroadcast()` / `sendOrderedBroadcast()` | Blocked | `SecurityException` -- prevents sending system broadcasts |
| `registerReceiver()` | Blocked | `SecurityException` -- prevents intercepting system broadcasts |
| `getContentResolver()` | Blocked | `SecurityException` -- prevents accessing other apps' data |
| `createPackageContext()` | Blocked | `SecurityException` -- prevents accessing other apps |
| `getBaseContext()` | Blocked | `SecurityException` -- prevents escaping the sandbox |
| `getApplicationContext()` | Returns restricted self | Trapped -- prevents escape |
| `getSystemService()` | **Allowlisted** | Hardware services only: `BluetoothManager`, `LocationManager`, `PowerManager`, `AlarmManager`, `SensorManager`, `UsbManager`, `WifiManager`. All others throw `SecurityException`. |
| `getSharedPreferences()` | Blocked | `SecurityException` -- prevents cross-plugin credential access |
| `credentialProvider.*` | **Per-plugin scoped** | Isolated `SharedPreferences` namespaced by plugin ID |
| `settingsStore` | Allowed | Full access (per-plugin namespace) |
| `debugLogger` | Allowed | Full access |
| `eventBus` | Allowed | Full access (platform-only events still blocked) |
| `safetyLimits` | Allowed | Read-only `StateFlow` |
| `filesDir` / `cacheDir` | Allowed | Full access |

Compile-time plugins (like Tandem) receive the full, unrestricted `PluginContext`.

**Known limitation:** Runtime plugins are loaded in-process via `DexClassLoader` with the app's classloader as parent. This means plugins can theoretically load and reflect over host app classes beyond the `pump-driver-api` interfaces. Full process-level isolation would require running plugins in a separate Android process, which adds significant complexity. The current approach relies on the trust model (users explicitly install plugins with a security warning) and is appropriate for community-developed monitoring plugins.

### Building a Runtime Plugin

See `plugins/example/` for a complete reference project. The general steps are:

1. Create a Kotlin/Java project that depends on `pump-driver-api` (compile-only)
2. Implement `PluginFactory` (no-arg constructor) and `Plugin`
3. Add `META-INF/plugin.json` manifest
4. Compile to `.class` files, then convert to DEX with `d8`
5. Package manifest into the DEX JAR
6. Install via the app's UI or `adb push`

### Compile-Time vs Runtime Comparison

| Feature | Compile-Time | Runtime |
|---------|-------------|---------|
| Discovery | Hilt `@IntoSet` multibindings | `DexClassLoader` + manifest |
| Android Context | Full `Context` | `RestrictedContext` |
| Credential Access | Full `PumpCredentialProvider` | Per-plugin scoped (`ScopedCredentialProvider`) |
| Safety Limits | Read-only `StateFlow` | Read-only `StateFlow` |
| Event Bus | Full (platform events blocked) | Full (platform events blocked) |
| Settings Store | Per-plugin `SharedPreferences` | Per-plugin `SharedPreferences` |
| Can be removed? | No (built into APK) | Yes (via Settings UI) |
| Shipped in APK | Yes | No (user installs manually) |

---

## ProGuard Rules

Plugin API interfaces and domain models must be kept for capability reflection. The following rules are included in `:app`'s `proguard-rules.pro`:

```proguard
# Plugin API interfaces and domain models (needed for capability reflection)
-keep class com.glycemicgpt.mobile.domain.plugin.** { *; }
-keep class com.glycemicgpt.mobile.domain.pump.** { *; }
-keep class com.glycemicgpt.mobile.domain.model.** { *; }
```

If your plugin module introduces new classes that are accessed via reflection or `KClass` references, add corresponding keep rules in your module's ProGuard configuration.
