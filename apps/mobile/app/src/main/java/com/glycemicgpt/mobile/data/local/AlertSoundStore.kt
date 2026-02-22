package com.glycemicgpt.mobile.data.local

import android.content.Context
import android.content.SharedPreferences
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

enum class AlertSoundCategory {
    LOW_ALERT,
    HIGH_ALERT,
    AI_NOTIFICATION,
}

/**
 * Persists per-category alert sound URIs and notification channel versions.
 *
 * Channel versions are incremented each time a sound is changed, because
 * Android's [NotificationChannel] sound is immutable after creation.
 * The old channel is deleted and a new one created with the bumped version ID.
 */
@Singleton
class AlertSoundStore @Inject constructor(
    @ApplicationContext context: Context,
) {

    private val prefs: SharedPreferences =
        context.getSharedPreferences("alert_sounds", Context.MODE_PRIVATE)

    // --- Sound URIs (null = system default) ---

    var lowAlertSoundUri: String?
        get() = prefs.getString(KEY_LOW_SOUND_URI, null)
        set(value) {
            prefs.edit().putString(KEY_LOW_SOUND_URI, value).apply()
        }

    var highAlertSoundUri: String?
        get() = prefs.getString(KEY_HIGH_SOUND_URI, null)
        set(value) {
            prefs.edit().putString(KEY_HIGH_SOUND_URI, value).apply()
        }

    var aiNotificationSoundUri: String?
        get() = prefs.getString(KEY_AI_SOUND_URI, null)
        set(value) {
            prefs.edit().putString(KEY_AI_SOUND_URI, value).apply()
        }

    // --- Display name cache ---

    var lowAlertSoundName: String?
        get() = prefs.getString(KEY_LOW_SOUND_NAME, null)
        set(value) {
            prefs.edit().putString(KEY_LOW_SOUND_NAME, value).apply()
        }

    var highAlertSoundName: String?
        get() = prefs.getString(KEY_HIGH_SOUND_NAME, null)
        set(value) {
            prefs.edit().putString(KEY_HIGH_SOUND_NAME, value).apply()
        }

    var aiNotificationSoundName: String?
        get() = prefs.getString(KEY_AI_SOUND_NAME, null)
        set(value) {
            prefs.edit().putString(KEY_AI_SOUND_NAME, value).apply()
        }

    // --- Override silent mode ---

    var overrideSilentForLowAlerts: Boolean
        get() = prefs.getBoolean(KEY_OVERRIDE_SILENT, true)
        set(value) {
            prefs.edit().putBoolean(KEY_OVERRIDE_SILENT, value).apply()
        }

    // --- Channel versions ---

    var lowChannelVersion: Int
        get() = prefs.getInt(KEY_LOW_CHANNEL_VERSION, 1)
        set(value) {
            prefs.edit().putInt(KEY_LOW_CHANNEL_VERSION, value).apply()
        }

    var highChannelVersion: Int
        get() = prefs.getInt(KEY_HIGH_CHANNEL_VERSION, 1)
        set(value) {
            prefs.edit().putInt(KEY_HIGH_CHANNEL_VERSION, value).apply()
        }

    var aiChannelVersion: Int
        get() = prefs.getInt(KEY_AI_CHANNEL_VERSION, 1)
        set(value) {
            prefs.edit().putInt(KEY_AI_CHANNEL_VERSION, value).apply()
        }

    fun getSoundUri(category: AlertSoundCategory): String? = when (category) {
        AlertSoundCategory.LOW_ALERT -> lowAlertSoundUri
        AlertSoundCategory.HIGH_ALERT -> highAlertSoundUri
        AlertSoundCategory.AI_NOTIFICATION -> aiNotificationSoundUri
    }

    fun setSoundUri(category: AlertSoundCategory, uri: String?) {
        when (category) {
            AlertSoundCategory.LOW_ALERT -> lowAlertSoundUri = uri
            AlertSoundCategory.HIGH_ALERT -> highAlertSoundUri = uri
            AlertSoundCategory.AI_NOTIFICATION -> aiNotificationSoundUri = uri
        }
    }

    fun getSoundName(category: AlertSoundCategory): String? = when (category) {
        AlertSoundCategory.LOW_ALERT -> lowAlertSoundName
        AlertSoundCategory.HIGH_ALERT -> highAlertSoundName
        AlertSoundCategory.AI_NOTIFICATION -> aiNotificationSoundName
    }

    fun setSoundName(category: AlertSoundCategory, name: String?) {
        when (category) {
            AlertSoundCategory.LOW_ALERT -> lowAlertSoundName = name
            AlertSoundCategory.HIGH_ALERT -> highAlertSoundName = name
            AlertSoundCategory.AI_NOTIFICATION -> aiNotificationSoundName = name
        }
    }

    fun getChannelVersion(category: AlertSoundCategory): Int = when (category) {
        AlertSoundCategory.LOW_ALERT -> lowChannelVersion
        AlertSoundCategory.HIGH_ALERT -> highChannelVersion
        AlertSoundCategory.AI_NOTIFICATION -> aiChannelVersion
    }

    /**
     * Increments and returns the new channel version for [category].
     *
     * **Threading**: This performs a non-atomic read-modify-write on SharedPreferences.
     * Callers must hold `AlertNotificationManager.channelLock` to prevent concurrent
     * increments from producing duplicate version numbers.
     */
    fun incrementChannelVersion(category: AlertSoundCategory): Int {
        val newVersion = getChannelVersion(category) + 1
        when (category) {
            AlertSoundCategory.LOW_ALERT -> lowChannelVersion = newVersion
            AlertSoundCategory.HIGH_ALERT -> highChannelVersion = newVersion
            AlertSoundCategory.AI_NOTIFICATION -> aiChannelVersion = newVersion
        }
        return newVersion
    }

    companion object {
        /**
         * Sentinel value stored in SharedPreferences to indicate the user explicitly
         * chose "Silent" from the ringtone picker. Distinguishes from `null` which
         * means "no preference set, use system default".
         */
        const val SILENT_URI = "silent"

        private const val KEY_LOW_SOUND_URI = "low_alert_sound_uri"
        private const val KEY_HIGH_SOUND_URI = "high_alert_sound_uri"
        private const val KEY_AI_SOUND_URI = "ai_notification_sound_uri"
        private const val KEY_LOW_SOUND_NAME = "low_alert_sound_name"
        private const val KEY_HIGH_SOUND_NAME = "high_alert_sound_name"
        private const val KEY_AI_SOUND_NAME = "ai_notification_sound_name"
        private const val KEY_OVERRIDE_SILENT = "override_silent_for_low"
        private const val KEY_LOW_CHANNEL_VERSION = "low_channel_version"
        private const val KEY_HIGH_CHANNEL_VERSION = "high_channel_version"
        private const val KEY_AI_CHANNEL_VERSION = "ai_channel_version"
    }
}
