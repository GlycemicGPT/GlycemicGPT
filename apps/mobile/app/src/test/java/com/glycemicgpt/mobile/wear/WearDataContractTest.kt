package com.glycemicgpt.mobile.wear

import org.junit.Assert.assertEquals
import org.junit.Test

class WearDataContractTest {

    @Test
    fun `IOB_PATH matches expected value`() {
        assertEquals("/glycemicgpt/iob", WearDataContract.IOB_PATH)
    }

    @Test
    fun `CGM_PATH matches expected value`() {
        assertEquals("/glycemicgpt/cgm", WearDataContract.CGM_PATH)
    }

    @Test
    fun `data contract keys are consistent`() {
        assertEquals("iob", WearDataContract.KEY_IOB_VALUE)
        assertEquals("iob_ts", WearDataContract.KEY_IOB_TIMESTAMP)
        assertEquals("cgm_mgdl", WearDataContract.KEY_CGM_MG_DL)
        assertEquals("cgm_trend", WearDataContract.KEY_CGM_TREND)
        assertEquals("cgm_ts", WearDataContract.KEY_CGM_TIMESTAMP)
        assertEquals("glucose_low", WearDataContract.KEY_GLUCOSE_LOW)
        assertEquals("glucose_high", WearDataContract.KEY_GLUCOSE_HIGH)
        assertEquals("glucose_urg_low", WearDataContract.KEY_GLUCOSE_URGENT_LOW)
        assertEquals("glucose_urg_high", WearDataContract.KEY_GLUCOSE_URGENT_HIGH)
    }

    @Test
    fun `ALERT_PATH matches expected value`() {
        assertEquals("/glycemicgpt/alert", WearDataContract.ALERT_PATH)
    }

    @Test
    fun `alert keys are consistent`() {
        assertEquals("alert_type", WearDataContract.KEY_ALERT_TYPE)
        assertEquals("alert_bg", WearDataContract.KEY_ALERT_BG_VALUE)
        assertEquals("alert_ts", WearDataContract.KEY_ALERT_TIMESTAMP)
        assertEquals("alert_msg", WearDataContract.KEY_ALERT_MESSAGE)
    }

    @Test
    fun `CHAT paths match expected values`() {
        assertEquals("/glycemicgpt/chat/request", WearDataContract.CHAT_REQUEST_PATH)
        assertEquals("/glycemicgpt/chat/response", WearDataContract.CHAT_RESPONSE_PATH)
        assertEquals("/glycemicgpt/chat/error", WearDataContract.CHAT_ERROR_PATH)
    }

    @Test
    fun `capability constants match expected values`() {
        assertEquals("glycemicgpt_chat_relay", WearDataContract.CHAT_RELAY_CAPABILITY)
        assertEquals("glycemicgpt_watch_app", WearDataContract.WATCH_APP_CAPABILITY)
    }

    @Test
    fun `CONFIG_PATH matches expected value`() {
        assertEquals("/glycemicgpt/watchface/config", WearDataContract.CONFIG_PATH)
    }

    @Test
    fun `config keys are consistent`() {
        assertEquals("cfg_show_iob", WearDataContract.KEY_CONFIG_SHOW_IOB)
        assertEquals("cfg_show_graph", WearDataContract.KEY_CONFIG_SHOW_GRAPH)
        assertEquals("cfg_show_alert", WearDataContract.KEY_CONFIG_SHOW_ALERT)
        assertEquals("cfg_show_seconds", WearDataContract.KEY_CONFIG_SHOW_SECONDS)
        assertEquals("cfg_graph_range_h", WearDataContract.KEY_CONFIG_GRAPH_RANGE_HOURS)
        assertEquals("cfg_theme", WearDataContract.KEY_CONFIG_THEME)
    }
}
