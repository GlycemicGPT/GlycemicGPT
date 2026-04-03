# Demo Glucometer Plugin

A comprehensive reference plugin demonstrating the full GlycemicGPT plugin API by simulating a Bluetooth glucose meter.

## What This Plugin Does

This plugin implements `BGM_SOURCE` and `DATA_SYNC` capabilities, showcasing every plugin API feature:

- **Dashboard Cards** -- LargeValue, StatusBadge, Row, IconValue, SparkLine, ProgressBar
- **Settings UI** -- Toggle, Slider, Dropdown, TextInput, ActionButton, InfoText
- **Event Bus** -- Publishing NewBgmReading events for cross-plugin workflows
- **Safety Limits** -- Validating readings against platform-enforced glucose bounds
- **Settings Persistence** -- Reading/writing plugin config via PluginSettingsStore
- **BgmSource Capability** -- Implementing a typed capability interface
- **Credential Storage** -- Per-plugin scoped credential provider (runtime plugins)

Use this as a template when building real pump, CGM, or BGM drivers.

## Building

### Prerequisites

1. Android SDK with `d8` tool (included in Android build tools)
2. The `pump-driver-api` module compiled as an AAR or JAR

### Steps

1. **Compile the plugin:**

   If building within the GlycemicGPT monorepo (for testing):
   ```bash
   cd plugins/example
   ../../gradlew jar
   ```

   If building standalone, first copy the pump-driver-api AAR to `libs/` and uncomment the `compileOnly(files(...))` line in `build.gradle.kts`.

2. **Convert to DEX bytecode:**

   Android cannot run standard JVM bytecode. Use `d8` to convert:
   ```bash
   d8 --output dex-out/ build/libs/example-plugin.jar
   ```

3. **Repackage DEX + manifest into the final JAR:**

   The `d8` tool outputs `classes.dex` to a directory. Combine it with the
   original JAR (which has the manifest):
   ```bash
   cp build/libs/example-plugin.jar example-plugin.jar
   jar uf example-plugin.jar -C dex-out classes.dex
   ```

4. **Install on device:**

   Option A -- Use the app's UI:
   - Copy `example-plugin.jar` to your phone
   - Open Settings > Plugins > Custom Plugins > Add Plugin
   - Select the JAR file

   Option B -- Use adb (debug builds only, non-rooted device):
   ```bash
   adb push example-plugin.jar /sdcard/example-plugin.jar
   adb shell run-as com.glycemicgpt.mobile.debug \
       mkdir -p files/plugins
   adb shell run-as com.glycemicgpt.mobile.debug \
       cp /sdcard/example-plugin.jar files/plugins/
   adb shell rm /sdcard/example-plugin.jar
   ```
   Then restart the app. Replace `com.glycemicgpt.mobile.debug` with the
   correct package name for your build variant.

## Plugin Manifest

Every runtime plugin JAR must contain `META-INF/plugin.json`:

```json
{
  "factoryClass": "com.example.glycemicgpt.plugin.DemoGlucometerFactory",
  "apiVersion": 1,
  "id": "com.example.glycemicgpt.demo-glucometer",
  "name": "Demo Glucometer",
  "version": "1.0.0",
  "author": "GlycemicGPT",
  "description": "Comprehensive plugin showcase simulating a Bluetooth glucose meter."
}
```

### Required Fields

| Field | Description |
|-------|-------------|
| `factoryClass` | Fully-qualified class name of your `PluginFactory` implementation |
| `apiVersion` | Must match the host app's `PLUGIN_API_VERSION` (currently `1`) |
| `id` | Reverse-domain plugin ID (must match `^[a-zA-Z][a-zA-Z0-9._-]{1,127}$`) |
| `name` | Human-readable display name |
| `version` | Semantic version string |

### Optional Fields

| Field | Description |
|-------|-------------|
| `author` | Author name (displayed in Settings) |
| `description` | Short description |

## Security Model

Runtime plugins run in a sandboxed context that blocks app-scope escape vectors while allowing hardware access:

**Blocked** (prevents host app hijacking):
- `startActivity()`, `startService()` -- can't launch arbitrary components
- `getContentResolver()` -- can't access other apps' content providers
- `sendBroadcast()` -- can't send system broadcasts
- `getBaseContext()` -- can't escape the sandbox wrapper

**Allowed** (needed for BLE device drivers):
- `getSystemService()` -- BluetoothManager, LocationManager, PowerManager, etc.
- `credentialProvider` -- per-plugin scoped credential storage (isolated by plugin ID)
- `settingsStore` -- per-plugin key-value persistence
- `debugLogger` -- logging
- `eventBus` -- cross-plugin communication (platform-only events blocked)
- `safetyLimits` -- read-only safety constraints
- `androidContext.filesDir`, `cacheDir`, etc. -- file I/O

Safety enforcement comes from `SafetyLimits` (synced from backend), not Context restrictions.

## Further Reading

See [docs/plugin-architecture.md](../../docs/plugin-architecture.md) for the full plugin API documentation.
