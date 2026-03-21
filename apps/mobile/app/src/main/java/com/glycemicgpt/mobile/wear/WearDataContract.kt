package com.glycemicgpt.mobile.wear

// MIRROR: This contract must stay in sync with
// wear-device/src/main/java/com/glycemicgpt/weardevice/data/WearDataContract.kt
object WearDataContract {
    // DataClient paths (persistent state sync)
    const val IOB_PATH = "/glycemicgpt/iob"
    const val CGM_PATH = "/glycemicgpt/cgm"
    const val ALERT_PATH = "/glycemicgpt/alert"

    // DataClient paths for history overlays (phone -> watch)
    const val BASAL_HISTORY_PATH = "/glycemicgpt/history/basal"
    const val BOLUS_HISTORY_PATH = "/glycemicgpt/history/bolus"
    const val IOB_HISTORY_PATH = "/glycemicgpt/history/iob"

    // History payload keys (compact byte arrays)
    const val KEY_HISTORY_DATA = "history_data"
    const val KEY_HISTORY_COUNT = "history_count"

    // IoB keys
    const val KEY_IOB_VALUE = "iob"
    const val KEY_IOB_TIMESTAMP = "iob_ts"

    // CGM keys
    const val KEY_CGM_MG_DL = "cgm_mgdl"
    const val KEY_CGM_TREND = "cgm_trend"
    const val KEY_CGM_TIMESTAMP = "cgm_ts"
    const val KEY_GLUCOSE_LOW = "glucose_low"
    const val KEY_GLUCOSE_HIGH = "glucose_high"
    const val KEY_GLUCOSE_URGENT_LOW = "glucose_urg_low"
    const val KEY_GLUCOSE_URGENT_HIGH = "glucose_urg_high"

    // Alert keys
    const val KEY_ALERT_TYPE = "alert_type"
    const val KEY_ALERT_BG_VALUE = "alert_bg"
    const val KEY_ALERT_TIMESTAMP = "alert_ts"
    const val KEY_ALERT_MESSAGE = "alert_msg"

    // MessageClient paths (transient chat relay)
    const val CHAT_REQUEST_PATH = "/glycemicgpt/chat/request"
    const val CHAT_RESPONSE_PATH = "/glycemicgpt/chat/response"
    const val CHAT_ERROR_PATH = "/glycemicgpt/chat/error"

    // Alert dismiss path (watch -> phone)
    const val ALERT_DISMISS_PATH = "/glycemicgpt/alert/dismiss"

    // ChannelClient paths (large data transfer)
    const val WATCHFACE_PUSH_CHANNEL = "/glycemicgpt/watchface/push"
    const val WATCH_APK_PUSH_CHANNEL = "/glycemicgpt/watch/apk/push"

    // Watch Face Push status paths (watch -> phone via MessageClient)
    const val WATCHFACE_PUSH_STATUS_PATH = "/glycemicgpt/watchface/status"

    // Watch APK self-update status path (watch -> phone via MessageClient)
    const val WATCH_APK_PUSH_STATUS_PATH = "/glycemicgpt/watch/apk/status"

    // Watch version sync path (watch -> phone via DataClient)
    const val WATCH_VERSION_PATH = "/glycemicgpt/watch/version"

    // Watch version keys
    const val KEY_WATCH_VERSION_NAME = "watch_ver_name"
    const val KEY_WATCH_VERSION_CODE = "watch_ver_code"
    const val KEY_WATCH_UPDATE_CHANNEL = "watch_update_ch"
    const val KEY_WATCH_DEV_BUILD_NUMBER = "watch_dev_build"

    // Watch face config sync path (phone -> watch via DataClient)
    const val CONFIG_PATH = "/glycemicgpt/watchface/config"

    // Watch face config keys
    const val KEY_CONFIG_SHOW_IOB = "cfg_show_iob"
    const val KEY_CONFIG_SHOW_GRAPH = "cfg_show_graph"
    const val KEY_CONFIG_SHOW_ALERT = "cfg_show_alert"
    const val KEY_CONFIG_SHOW_SECONDS = "cfg_show_seconds"
    const val KEY_CONFIG_GRAPH_RANGE_HOURS = "cfg_graph_range_h"
    const val KEY_CONFIG_THEME = "cfg_theme"
    const val KEY_CONFIG_SHOW_BASAL = "cfg_show_basal"
    const val KEY_CONFIG_SHOW_BOLUS = "cfg_show_bolus"
    const val KEY_CONFIG_SHOW_IOB_OVERLAY = "cfg_show_iob_ovl"
    const val KEY_CONFIG_SHOW_MODES = "cfg_show_modes"

    // CapabilityClient capabilities
    const val CHAT_RELAY_CAPABILITY = "glycemicgpt_chat_relay"
    const val WATCH_APP_CAPABILITY = "glycemicgpt_watch_app"

    // Watch face theme keys (must match WFF UserConfiguration values)
    const val THEME_DARK = "dark"
    const val THEME_CLINICAL_BLUE = "clinical_blue"
    const val THEME_HIGH_CONTRAST = "high_contrast"

    /** Builds a DataClient URI for querying data items across all nodes. */
    fun dataUri(path: String): android.net.Uri =
        android.net.Uri.parse("wear://*$path")
}
