package com.glycemicgpt.weardevice.data

object WearDataContract {
    // DataClient paths (persistent state sync)
    const val IOB_PATH = "/glycemicgpt/iob"
    const val CGM_PATH = "/glycemicgpt/cgm"
    const val ALERT_PATH = "/glycemicgpt/alert"

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

    // Watch Face Push status paths (watch -> phone via MessageClient)
    const val WATCHFACE_PUSH_STATUS_PATH = "/glycemicgpt/watchface/status"

    // CapabilityClient capabilities
    const val CHAT_RELAY_CAPABILITY = "glycemicgpt_chat_relay"
    const val WATCH_APP_CAPABILITY = "glycemicgpt_watch_app"
}
