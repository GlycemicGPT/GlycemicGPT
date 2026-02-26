package com.glycemicgpt.mobile.plugin

import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.ContentResolver
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.IntentFilter
import android.content.ServiceConnection
import android.content.SharedPreferences
import android.os.Bundle
import android.os.Handler
import com.glycemicgpt.mobile.domain.plugin.PLUGIN_API_VERSION
import com.glycemicgpt.mobile.domain.plugin.PluginContext
import com.glycemicgpt.mobile.domain.pump.DebugLogger
import com.glycemicgpt.mobile.domain.pump.PumpCredentialProvider
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import com.glycemicgpt.mobile.domain.plugin.events.PluginEventBus
import kotlinx.coroutines.flow.StateFlow

/**
 * Creates a [PluginContext] with restricted internals for runtime-loaded plugins.
 *
 * Compile-time plugins get full access to the application context and credential
 * provider. Runtime plugins get:
 * - [RestrictedContext]: blocks app-scope escape vectors (startActivity, startActivities,
 *   startService, sendBroadcast, registerReceiver, getContentResolver,
 *   createPackageContext, getBaseContext). Allows hardware-related system services
 *   via an allowlist (BluetoothManager, LocationManager, etc.).
 *   Returns self for getApplicationContext() to prevent escape.
 * - [ScopedCredentialProvider]: per-plugin isolated credential storage namespaced
 *   by plugin ID, so each runtime plugin's pairing data is separate. Uses the
 *   unrestricted base context for SharedPreferences access (SharedPreferences is
 *   per-app sandboxed by Android, and the plugin ID namespace prevents cross-plugin access).
 * - Full access to settingsStore, debugLogger, eventBus, safetyLimits
 *
 * Safety enforcement comes from [SafetyLimits] (synced from backend), not from
 * blanket Context restrictions. Plugins need hardware access to function as
 * pump/CGM/BGM drivers.
 */
object RestrictedPluginContext {

    fun create(
        baseContext: Context,
        pluginId: String,
        settingsStore: com.glycemicgpt.mobile.domain.plugin.PluginSettingsStore,
        debugLogger: DebugLogger,
        eventBus: PluginEventBus,
        safetyLimits: StateFlow<SafetyLimits>,
    ): PluginContext {
        require(pluginId.isNotBlank()) { "pluginId must not be blank" }
        val restrictedContext = RestrictedContext(baseContext)
        return PluginContext(
            androidContext = restrictedContext,
            pluginId = pluginId,
            settingsStore = settingsStore,
            credentialProvider = ScopedCredentialProvider(pluginId, baseContext),
            debugLogger = debugLogger,
            eventBus = eventBus,
            safetyLimits = safetyLimits,
            apiVersion = PLUGIN_API_VERSION,
        )
    }
}

/**
 * A [ContextWrapper] that blocks app-scope escape vectors for runtime plugins.
 *
 * **Blocked** (prevents plugins from hijacking the host app):
 * - startActivity / startActivities -- can't launch arbitrary UI
 * - startService / startForegroundService / bindService / stopService -- can't start services
 * - sendBroadcast / sendOrderedBroadcast -- can't send system broadcasts
 * - registerReceiver (all overloads) -- can't intercept system broadcasts
 * - getContentResolver -- can't access other apps' content providers
 * - createPackageContext -- can't access other apps' contexts
 * - getBaseContext -- can't escape the sandbox wrapper
 * - getSystemService for non-hardware services -- allowlist enforced
 *
 * **Allowed** (needed for BLE pump/CGM drivers):
 * - getSystemService for hardware-related services only (BluetoothManager, LocationManager,
 *   PowerManager, AlarmManager, SensorManager, UsbManager)
 * - getApplicationContext -- returns self (trapped, prevents escape)
 * - getFilesDir, getCacheDir, getPackageName, etc. -- safe read-only operations
 *
 * **Also blocked** (prevents cross-plugin data access):
 * - getSharedPreferences -- can't read other plugins' credential storage
 * - openFileOutput / openFileInput / deleteFile / getDir -- can't access app's internal files
 * - openOrCreateDatabase / deleteDatabase / getDatabasePath -- can't access databases
 * - createDeviceProtectedStorageContext -- can't escape to unencrypted storage
 */
internal class RestrictedContext(base: Context) : ContextWrapper(base) {

    private fun denied(operation: String): Nothing =
        throw SecurityException("Runtime plugins cannot call $operation")

    // Prevent sandbox escape via getApplicationContext() or getBaseContext()
    override fun getApplicationContext(): Context = this
    override fun getBaseContext(): Context = denied("getBaseContext")

    override fun startActivity(intent: Intent?) = denied("startActivity")
    override fun startActivity(intent: Intent?, options: Bundle?) = denied("startActivity")
    @Suppress("SpreadOperator")
    override fun startActivities(intents: Array<out Intent>?) = denied("startActivities")
    @Suppress("SpreadOperator")
    override fun startActivities(intents: Array<out Intent>?, options: Bundle?) =
        denied("startActivities")

    override fun startService(service: Intent?): ComponentName = denied("startService")
    override fun startForegroundService(service: Intent?): ComponentName = denied("startForegroundService")
    override fun stopService(name: Intent?): Boolean = denied("stopService")
    override fun bindService(service: Intent, conn: ServiceConnection, flags: Int): Boolean =
        denied("bindService")

    // getSystemService() is allowlisted to hardware-related services only.
    // Plugins need BluetoothManager, LocationManager (BLE scanning requires location on Android),
    // PowerManager, AlarmManager, etc. Non-hardware services (TelephonyManager, AccountManager,
    // ClipboardManager, etc.) are blocked to prevent data exfiltration.
    override fun getSystemService(name: String): Any? {
        if (name !in ALLOWED_SYSTEM_SERVICES) {
            denied("getSystemService($name)")
        }
        return super.getSystemService(name)
    }

    override fun getContentResolver(): ContentResolver = denied("getContentResolver")

    override fun sendBroadcast(intent: Intent?) = denied("sendBroadcast")
    override fun sendBroadcast(intent: Intent?, receiverPermission: String?) =
        denied("sendBroadcast")

    override fun sendOrderedBroadcast(intent: Intent, receiverPermission: String?) =
        denied("sendOrderedBroadcast")

    override fun sendOrderedBroadcast(intent: Intent, receiverPermission: String?, receiverAppOp: Bundle?) =
        denied("sendOrderedBroadcast")

    override fun sendOrderedBroadcast(
        intent: Intent,
        receiverPermission: String?,
        resultReceiver: BroadcastReceiver?,
        scheduler: Handler?,
        initialCode: Int,
        initialData: String?,
        initialExtras: Bundle?,
    ) = denied("sendOrderedBroadcast")

    override fun registerReceiver(
        receiver: BroadcastReceiver?,
        filter: IntentFilter?,
    ): Intent? = denied("registerReceiver")

    override fun registerReceiver(
        receiver: BroadcastReceiver?,
        filter: IntentFilter?,
        flags: Int,
    ): Intent? = denied("registerReceiver")

    override fun registerReceiver(
        receiver: BroadcastReceiver?,
        filter: IntentFilter?,
        broadcastPermission: String?,
        scheduler: Handler?,
    ): Intent? = denied("registerReceiver")

    override fun registerReceiver(
        receiver: BroadcastReceiver?,
        filter: IntentFilter?,
        broadcastPermission: String?,
        scheduler: Handler?,
        flags: Int,
    ): Intent? = denied("registerReceiver")

    // Block storage methods to prevent cross-plugin credential/data access.
    // ScopedCredentialProvider uses baseContext (not this RestrictedContext) for
    // its own namespaced SharedPreferences access.
    override fun getSharedPreferences(name: String?, mode: Int): SharedPreferences =
        denied("getSharedPreferences")

    override fun openFileOutput(name: String?, mode: Int): java.io.FileOutputStream =
        denied("openFileOutput")

    override fun openFileInput(name: String?): java.io.FileInputStream =
        denied("openFileInput")

    override fun deleteFile(name: String?): Boolean =
        denied("deleteFile")

    override fun getDir(name: String?, mode: Int): java.io.File =
        denied("getDir")

    override fun getDatabasePath(name: String?): java.io.File =
        denied("getDatabasePath")

    override fun openOrCreateDatabase(
        name: String?,
        mode: Int,
        factory: android.database.sqlite.SQLiteDatabase.CursorFactory?,
    ): android.database.sqlite.SQLiteDatabase = denied("openOrCreateDatabase")

    override fun openOrCreateDatabase(
        name: String?,
        mode: Int,
        factory: android.database.sqlite.SQLiteDatabase.CursorFactory?,
        errorHandler: android.database.DatabaseErrorHandler?,
    ): android.database.sqlite.SQLiteDatabase = denied("openOrCreateDatabase")

    override fun deleteDatabase(name: String?): Boolean =
        denied("deleteDatabase")

    override fun createDeviceProtectedStorageContext(): Context =
        denied("createDeviceProtectedStorageContext")

    override fun createPackageContext(packageName: String?, flags: Int): Context =
        denied("createPackageContext")

    companion object {
        /** System services allowed for runtime plugins (hardware/device access). */
        val ALLOWED_SYSTEM_SERVICES: Set<String> = setOf(
            Context.BLUETOOTH_SERVICE,     // BluetoothManager -- BLE device communication
            Context.LOCATION_SERVICE,      // LocationManager -- required for BLE scanning
            Context.POWER_SERVICE,         // PowerManager -- wake locks for BLE connections
            Context.ALARM_SERVICE,         // AlarmManager -- scheduling periodic reads
            Context.SENSOR_SERVICE,        // SensorManager -- hardware sensors
            Context.USB_SERVICE,           // UsbManager -- USB device plugins
            Context.WIFI_SERVICE,          // WifiManager -- network-connected devices
            // WINDOW_SERVICE intentionally excluded -- plugins don't need display metrics,
            // and WindowManager can add overlay views if SYSTEM_ALERT_WINDOW is held.
        )
    }
}

/**
 * Per-plugin scoped credential storage for runtime plugins.
 *
 * Each runtime plugin gets its own isolated [SharedPreferences] namespace
 * (keyed by a sanitized plugin ID), preventing cross-plugin credential access.
 * Compile-time plugins use the app's EncryptedSharedPreferences directly;
 * runtime plugins use regular SharedPreferences since credentials are
 * only accessible within the app's Android sandbox and plugin credentials
 * are for devices the user explicitly pairs with.
 *
 * **Note on encryption:** Regular SharedPreferences is used instead of
 * EncryptedSharedPreferences because runtime plugins cannot access AndroidX
 * Security library. On rooted/debug devices, credentials are readable via
 * `run-as`. This is acceptable for the current trust model (user-installed
 * plugins for personal device pairing). If the threat model changes to include
 * adversarial plugins, migration to EncryptedSharedPreferences is required.
 */
internal class ScopedCredentialProvider(
    private val pluginId: String,
    context: Context,
) : PumpCredentialProvider {

    private val prefs: SharedPreferences = context.getSharedPreferences(
        "plugin_creds_${sanitizeId(pluginId)}",
        Context.MODE_PRIVATE,
    )

    override fun getPairedAddress(): String? = prefs.getString(KEY_ADDRESS, null)

    override fun getPairingCode(): String? = prefs.getString(KEY_PAIRING_CODE, null)

    override fun isPaired(): Boolean = prefs.contains(KEY_ADDRESS)

    override fun savePairing(address: String, pairingCode: String) {
        prefs.edit()
            .putString(KEY_ADDRESS, address)
            .putString(KEY_PAIRING_CODE, pairingCode)
            .apply()
    }

    override fun clearPairing() {
        prefs.edit()
            .remove(KEY_ADDRESS)
            .remove(KEY_PAIRING_CODE)
            .apply()
    }

    override fun saveJpakeCredentials(derivedSecretHex: String, serverNonceHex: String) {
        prefs.edit()
            .putString(KEY_JPAKE_SECRET, derivedSecretHex)
            .putString(KEY_JPAKE_NONCE, serverNonceHex)
            .apply()
    }

    override fun getJpakeDerivedSecret(): String? = prefs.getString(KEY_JPAKE_SECRET, null)

    override fun getJpakeServerNonce(): String? = prefs.getString(KEY_JPAKE_NONCE, null)

    override fun clearJpakeCredentials() {
        prefs.edit()
            .remove(KEY_JPAKE_SECRET)
            .remove(KEY_JPAKE_NONCE)
            .apply()
    }

    companion object {
        private const val KEY_ADDRESS = "paired_address"
        private const val KEY_PAIRING_CODE = "pairing_code"
        private const val KEY_JPAKE_SECRET = "jpake_derived_secret"
        private const val KEY_JPAKE_NONCE = "jpake_server_nonce"

        /**
         * Sanitizes a plugin ID into a safe SharedPreferences filename component.
         * Only strips path-unsafe characters (slashes, null bytes) while preserving
         * dots, hyphens, and underscores to avoid namespace collisions between
         * distinct plugin IDs (e.g., `com.foo.bar-baz` vs `com.foo.bar.baz`
         * remain distinct).
         */
        internal fun sanitizeId(pluginId: String): String =
            pluginId.replace(Regex("[^a-zA-Z0-9._-]"), "_")
    }
}
