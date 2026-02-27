package com.glycemicgpt.mobile.data.local

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import dagger.hilt.android.qualifiers.ApplicationContext
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

    companion object {
        private const val OLD_PREFS_NAME = "app_settings"
        private const val ENCRYPTED_PREFS_NAME = "app_settings_encrypted"
        private const val KEY_ONBOARDING_COMPLETE = "onboarding_complete"
        private const val KEY_BACKEND_SYNC_ENABLED = "backend_sync_enabled"
        private const val KEY_DATA_RETENTION_DAYS = "data_retention_days"
        private const val KEY_DEVICE_TOKEN = "device_token"
        const val DEFAULT_RETENTION_DAYS = 7
        const val MIN_RETENTION_DAYS = 1
        const val MAX_RETENTION_DAYS = 30
    }
}
