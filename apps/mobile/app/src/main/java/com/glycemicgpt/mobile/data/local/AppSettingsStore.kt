package com.glycemicgpt.mobile.data.local

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.glycemicgpt.mobile.domain.model.GlucoseUnit
import com.glycemicgpt.mobile.presentation.theme.ThemeMode
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * App settings stored in EncryptedSharedPreferences (Story 28.8).
 *
 * Migrated from plain SharedPreferences to encrypted storage.
 * One-time migration reads from old prefs, writes to encrypted, then deletes old file.
 */
@Singleton
class AppSettingsStore @Inject constructor(
    @ApplicationContext context: Context,
) {

    private val prefs: SharedPreferences by lazy {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        val encPrefs = EncryptedSharedPreferences.create(
            context,
            ENCRYPTED_PREFS_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
        // One-time migration from plain SharedPreferences
        migrateFromPlainPrefs(context, encPrefs)
        encPrefs
    }

    private fun migrateFromPlainPrefs(context: Context, encPrefs: SharedPreferences) {
        val oldPrefs = context.getSharedPreferences(OLD_PREFS_NAME, Context.MODE_PRIVATE)
        if (oldPrefs.all.isEmpty()) return

        // Only migrate if encrypted prefs are empty (first run after upgrade)
        if (encPrefs.all.isNotEmpty()) {
            // Already migrated; delete old file if it still exists
            val deleted = deleteOldPrefs(context)
            if (!deleted) {
                Timber.w("Encrypted prefs exist but failed to delete legacy plain prefs; will retry")
            }
            return
        }

        Timber.i("Migrating app settings from plain to encrypted SharedPreferences")
        val editor = encPrefs.edit()
        editor.putBoolean(KEY_ONBOARDING_COMPLETE, oldPrefs.getBoolean(KEY_ONBOARDING_COMPLETE, false))
        editor.putBoolean(KEY_BACKEND_SYNC_ENABLED, oldPrefs.getBoolean(KEY_BACKEND_SYNC_ENABLED, true))
        editor.putInt(KEY_DATA_RETENTION_DAYS, oldPrefs.getInt(KEY_DATA_RETENTION_DAYS, DEFAULT_RETENTION_DAYS))
        val token = oldPrefs.getString(KEY_DEVICE_TOKEN, null)
        if (token != null) {
            editor.putString(KEY_DEVICE_TOKEN, token)
        }
        val migrated = editor.commit()
        if (migrated) {
            val deleted = deleteOldPrefs(context)
            if (deleted) {
                Timber.i("Migration complete; old plain prefs deleted")
            } else {
                Timber.w("Migration committed, but failed to delete old plain prefs; will retry")
            }
        } else {
            Timber.w("Failed to commit migrated prefs; will retry on next launch")
        }
    }

    private fun deleteOldPrefs(context: Context): Boolean {
        return context.deleteSharedPreferences(OLD_PREFS_NAME)
    }

    var onboardingComplete: Boolean
        get() = prefs.getBoolean(KEY_ONBOARDING_COMPLETE, false)
        set(value) {
            prefs.edit().putBoolean(KEY_ONBOARDING_COMPLETE, value).apply()
        }

    var backendSyncEnabled: Boolean
        get() = prefs.getBoolean(KEY_BACKEND_SYNC_ENABLED, true)
        set(value) {
            prefs.edit().putBoolean(KEY_BACKEND_SYNC_ENABLED, value).apply()
        }

    var dataRetentionDays: Int
        get() = prefs.getInt(KEY_DATA_RETENTION_DAYS, DEFAULT_RETENTION_DAYS)
        set(value) {
            prefs.edit().putInt(KEY_DATA_RETENTION_DAYS, value.coerceIn(MIN_RETENTION_DAYS, MAX_RETENTION_DAYS)).apply()
        }

    var deviceToken: String?
        get() = prefs.getString(KEY_DEVICE_TOKEN, null)
        set(value) {
            if (value != null) {
                prefs.edit().putString(KEY_DEVICE_TOKEN, value).apply()
            } else {
                prefs.edit().remove(KEY_DEVICE_TOKEN).apply()
            }
        }

    /** Debug-only toggle: show pump-native category labels alongside display labels. */
    var showPumpLabels: Boolean
        get() = prefs.getBoolean(KEY_SHOW_PUMP_LABELS, false)
        set(value) {
            prefs.edit().putBoolean(KEY_SHOW_PUMP_LABELS, value).apply()
        }

    /** User-selected theme: System, Dark, or Light. */
    var themeMode: ThemeMode
        get() {
            val stored = prefs.getString(KEY_THEME_MODE, ThemeMode.System.name)
            return try {
                ThemeMode.valueOf(stored ?: ThemeMode.System.name)
            } catch (_: IllegalArgumentException) {
                ThemeMode.System
            }
        }
        set(value) {
            prefs.edit().putString(KEY_THEME_MODE, value.name).apply()
        }

    /**
     * User-selected glucose display unit. The unit is a *per-account* preference
     * (PATCHed to the backend and reconciled from it); this stored value is only
     * an offline cache / pre-sync fallback. Stored as the enum name, mirroring the
     * [themeMode] string-stored pattern, and defaults to [GlucoseUnit.MGDL] before
     * the first backend sync.
     */
    var glucoseUnit: GlucoseUnit
        get() = GlucoseUnit.fromName(prefs.getString(KEY_GLUCOSE_UNIT, GlucoseUnit.MGDL.name))
        set(value) {
            prefs.edit().putString(KEY_GLUCOSE_UNIT, value.name).apply()
        }

    /**
     * Whether the current [glucoseUnit] is a still-unconfirmed smart default
     * (server provenance "seed") with a non-mgdl value, so Settings should show
     * the one-time confirmation notice. Reconciled from
     * `GET /api/settings/glucose-unit`; cleared when the user confirms (toggles
     * the unit or dismisses the notice) and reset on logout. Local cache only --
     * the account value remains the source of truth.
     */
    var glucoseUnitSeedPending: Boolean
        get() = prefs.getBoolean(KEY_GLUCOSE_UNIT_SEED_PENDING, false)
        set(value) {
            prefs.edit().putBoolean(KEY_GLUCOSE_UNIT_SEED_PENDING, value).apply()
        }

    /**
     * Emits the current [glucoseUnit] and re-emits whenever it changes, so display
     * surfaces update live when the user toggles the unit or a backend reconcile
     * writes the cache. Uses the same change-listener mechanism the activity relies
     * on for live theme switching.
     */
    fun glucoseUnitFlow(): Flow<GlucoseUnit> = callbackFlow {
        trySend(glucoseUnit)
        val listener = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
            if (key == KEY_GLUCOSE_UNIT || key == null) {
                trySend(glucoseUnit)
            }
        }
        prefs.registerOnSharedPreferenceChangeListener(listener)
        awaitClose { prefs.unregisterOnSharedPreferenceChangeListener(listener) }
    }

    /**
     * Whether the meal-intelligence feature is enabled for this account. Gates the
     * meal surfaces (the "Log a meal" FAB + meal endpoints). A *per-account*
     * preference (PATCHed to the backend and reconciled from it); this stored
     * value is an offline cache / pre-sync fallback that defaults ON before the
     * first backend sync, mirroring the server default.
     */
    var mealIntelligenceEnabled: Boolean
        get() = prefs.getBoolean(KEY_MEAL_INTELLIGENCE_ENABLED, true)
        set(value) {
            prefs.edit().putBoolean(KEY_MEAL_INTELLIGENCE_ENABLED, value).apply()
        }

    /**
     * Emits the current [mealIntelligenceEnabled] and re-emits whenever it
     * changes, so the home FAB and meal surfaces appear/disappear live when the
     * user toggles the setting or a backend reconcile writes the cache. Uses the
     * same change-listener mechanism as [glucoseUnitFlow].
     */
    fun mealIntelligenceEnabledFlow(): Flow<Boolean> = callbackFlow {
        trySend(mealIntelligenceEnabled)
        val listener = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
            if (key == KEY_MEAL_INTELLIGENCE_ENABLED || key == null) {
                trySend(mealIntelligenceEnabled)
            }
        }
        prefs.registerOnSharedPreferenceChangeListener(listener)
        awaitClose { prefs.unregisterOnSharedPreferenceChangeListener(listener) }
    }

    /**
     * Persisted top-left position (px) of the draggable Home "Log a meal" FAB, or [UNSET_FAB_OFFSET]
     * on an axis the user has never set (fall back to the default bottom-end placement). Per-device
     * UI state only -- a local placement preference, never synced to the account. Read-only here;
     * write the pair atomically via [setMealFabOffset]. Bounds are intentionally enforced in the
     * placement layer (clampFabOffset), not on write, so a stale value self-corrects against the
     * live container size.
     */
    val mealFabOffsetXPx: Int
        get() = prefs.getInt(KEY_MEAL_FAB_OFFSET_X, UNSET_FAB_OFFSET)

    /** Persisted top-left Y (px) of the draggable Home meal FAB; see [mealFabOffsetXPx]. */
    val mealFabOffsetYPx: Int
        get() = prefs.getInt(KEY_MEAL_FAB_OFFSET_Y, UNSET_FAB_OFFSET)

    /** Persist the FAB position (px) as one atomic edit, so an interrupted write can't tear X from Y. */
    fun setMealFabOffset(x: Int, y: Int) {
        prefs.edit()
            .putInt(KEY_MEAL_FAB_OFFSET_X, x)
            .putInt(KEY_MEAL_FAB_OFFSET_Y, y)
            .apply()
    }

    /** Forget the saved FAB position so it falls back to the default bottom-end placement. */
    fun clearMealFabOffset() {
        prefs.edit()
            .remove(KEY_MEAL_FAB_OFFSET_X)
            .remove(KEY_MEAL_FAB_OFFSET_Y)
            .apply()
    }

    // Watch face config persistence
    var watchFaceShowIoB: Boolean
        get() = prefs.getBoolean(KEY_WATCHFACE_SHOW_IOB, true)
        set(value) { prefs.edit().putBoolean(KEY_WATCHFACE_SHOW_IOB, value).apply() }

    var watchFaceShowGraph: Boolean
        get() = prefs.getBoolean(KEY_WATCHFACE_SHOW_GRAPH, true)
        set(value) { prefs.edit().putBoolean(KEY_WATCHFACE_SHOW_GRAPH, value).apply() }

    var watchFaceShowAlert: Boolean
        get() = prefs.getBoolean(KEY_WATCHFACE_SHOW_ALERT, true)
        set(value) { prefs.edit().putBoolean(KEY_WATCHFACE_SHOW_ALERT, value).apply() }

    var watchFaceShowSeconds: Boolean
        get() = prefs.getBoolean(KEY_WATCHFACE_SHOW_SECONDS, false)
        set(value) { prefs.edit().putBoolean(KEY_WATCHFACE_SHOW_SECONDS, value).apply() }

    var watchFaceGraphRangeHours: Int
        get() = prefs.getInt(KEY_WATCHFACE_GRAPH_RANGE, 3)
        set(value) {
            val validated = if (value in VALID_WATCHFACE_GRAPH_RANGES) value else 3
            prefs.edit().putInt(KEY_WATCHFACE_GRAPH_RANGE, validated).apply()
        }

    var watchFaceTheme: String
        get() = prefs.getString(KEY_WATCHFACE_THEME, "Dark") ?: "Dark"
        set(value) { prefs.edit().putString(KEY_WATCHFACE_THEME, value).apply() }

    var watchFaceVariant: String
        get() = prefs.getString(KEY_WATCHFACE_VARIANT, "DIGITAL_FULL") ?: "DIGITAL_FULL"
        set(value) { prefs.edit().putString(KEY_WATCHFACE_VARIANT, value).apply() }

    var watchFaceShowBasalOverlay: Boolean
        get() = prefs.getBoolean(KEY_WATCHFACE_SHOW_BASAL, true)
        set(value) { prefs.edit().putBoolean(KEY_WATCHFACE_SHOW_BASAL, value).apply() }

    var watchFaceShowBolusMarkers: Boolean
        get() = prefs.getBoolean(KEY_WATCHFACE_SHOW_BOLUS, true)
        set(value) { prefs.edit().putBoolean(KEY_WATCHFACE_SHOW_BOLUS, value).apply() }

    var watchFaceShowIoBOverlay: Boolean
        get() = prefs.getBoolean(KEY_WATCHFACE_SHOW_IOB_OVERLAY, true)
        set(value) { prefs.edit().putBoolean(KEY_WATCHFACE_SHOW_IOB_OVERLAY, value).apply() }

    var watchFaceShowModeBands: Boolean
        get() = prefs.getBoolean(KEY_WATCHFACE_SHOW_MODES, true)
        set(value) { prefs.edit().putBoolean(KEY_WATCHFACE_SHOW_MODES, value).apply() }

    /**
     * Whether the app may connect to a self-hosted server over plaintext `http://` when the host is
     * a private/LAN address (Story 57.1). Default OFF -- enabling it is an explicit, acknowledged
     * choice. A *per-device* connection preference (the LAN box is the same across sign-ins), so it
     * is intentionally NOT reset on logout. Public hosts are always refused over http regardless of
     * this flag; enforcement lives in [com.glycemicgpt.mobile.data.remote.UrlSecurityPolicy].
     */
    var allowInsecureLanHttp: Boolean
        get() = prefs.getBoolean(KEY_ALLOW_INSECURE_LAN_HTTP, false)
        set(value) {
            prefs.edit().putBoolean(KEY_ALLOW_INSECURE_LAN_HTTP, value).apply()
        }

    /**
     * Emits the current [allowInsecureLanHttp] and re-emits whenever it changes, so the app-wide
     * insecure-HTTP indicator appears/disappears live when the user toggles the setting. Uses the
     * same change-listener mechanism as [glucoseUnitFlow].
     */
    fun allowInsecureLanHttpFlow(): Flow<Boolean> = callbackFlow {
        trySend(allowInsecureLanHttp)
        val listener = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
            if (key == KEY_ALLOW_INSECURE_LAN_HTTP || key == null) {
                trySend(allowInsecureLanHttp)
            }
        }
        prefs.registerOnSharedPreferenceChangeListener(listener)
        awaitClose { prefs.unregisterOnSharedPreferenceChangeListener(listener) }
    }

    /** Whether AI chat responses should be spoken aloud via TTS. */
    var aiTtsEnabled: Boolean
        get() = prefs.getBoolean(KEY_AI_TTS_ENABLED, false)
        set(value) { prefs.edit().putBoolean(KEY_AI_TTS_ENABLED, value).apply() }

    /** Selected TTS voice name (empty = system default). */
    var aiTtsVoice: String
        get() = prefs.getString(KEY_AI_TTS_VOICE, "") ?: ""
        set(value) { prefs.edit().putString(KEY_AI_TTS_VOICE, value).apply() }

    fun registerListener(listener: SharedPreferences.OnSharedPreferenceChangeListener) {
        prefs.registerOnSharedPreferenceChangeListener(listener)
    }

    fun unregisterListener(listener: SharedPreferences.OnSharedPreferenceChangeListener) {
        prefs.unregisterOnSharedPreferenceChangeListener(listener)
    }

    companion object {
        private val VALID_WATCHFACE_GRAPH_RANGES = listOf(1, 3, 6)
        private const val OLD_PREFS_NAME = "app_settings"
        internal const val ENCRYPTED_PREFS_NAME = "app_settings_encrypted"
        private const val KEY_ONBOARDING_COMPLETE = "onboarding_complete"
        private const val KEY_BACKEND_SYNC_ENABLED = "backend_sync_enabled"
        private const val KEY_DATA_RETENTION_DAYS = "data_retention_days"
        private const val KEY_DEVICE_TOKEN = "device_token"
        private const val KEY_SHOW_PUMP_LABELS = "show_pump_labels"
        internal const val KEY_THEME_MODE = "theme_mode"
        internal const val KEY_GLUCOSE_UNIT = "glucose_unit"
        internal const val KEY_GLUCOSE_UNIT_SEED_PENDING = "glucose_unit_seed_pending"
        internal const val KEY_MEAL_INTELLIGENCE_ENABLED = "meal_intelligence_enabled"
        private const val KEY_MEAL_FAB_OFFSET_X = "meal_fab_offset_x"
        private const val KEY_MEAL_FAB_OFFSET_Y = "meal_fab_offset_y"

        /** Sentinel for a meal-FAB offset the user has never set (use the default position). */
        const val UNSET_FAB_OFFSET = Int.MIN_VALUE
        const val DEFAULT_RETENTION_DAYS = 7
        const val MIN_RETENTION_DAYS = 1
        const val MAX_RETENTION_DAYS = 30
        private const val KEY_WATCHFACE_SHOW_IOB = "watchface_show_iob"
        private const val KEY_WATCHFACE_SHOW_GRAPH = "watchface_show_graph"
        private const val KEY_WATCHFACE_SHOW_ALERT = "watchface_show_alert"
        private const val KEY_WATCHFACE_SHOW_SECONDS = "watchface_show_seconds"
        private const val KEY_WATCHFACE_GRAPH_RANGE = "watchface_graph_range"
        private const val KEY_WATCHFACE_THEME = "watchface_theme"
        private const val KEY_WATCHFACE_VARIANT = "watchface_variant"
        private const val KEY_WATCHFACE_SHOW_BASAL = "watchface_show_basal"
        private const val KEY_WATCHFACE_SHOW_BOLUS = "watchface_show_bolus"
        private const val KEY_WATCHFACE_SHOW_IOB_OVERLAY = "watchface_show_iob_overlay"
        private const val KEY_WATCHFACE_SHOW_MODES = "watchface_show_modes"
        private const val KEY_AI_TTS_ENABLED = "ai_tts_enabled"
        private const val KEY_AI_TTS_VOICE = "ai_tts_voice"
        private const val KEY_ALLOW_INSECURE_LAN_HTTP = "allow_insecure_lan_http"
    }
}
