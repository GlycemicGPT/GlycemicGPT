package com.glycemicgpt.mobile.domain.plugin

import com.glycemicgpt.mobile.domain.plugin.ui.ButtonStyle
import com.glycemicgpt.mobile.domain.plugin.ui.SettingDescriptor
import org.junit.Assert.assertEquals
import org.junit.Test

class SettingDescriptorTest {

    @Test
    fun `TextInput has correct key`() {
        val textInput = SettingDescriptor.TextInput(
            key = "server_url",
            label = "Server URL",
            hint = "https://example.com",
        )

        assertEquals("server_url", textInput.key)
        assertEquals("Server URL", textInput.label)
        assertEquals("https://example.com", textInput.hint)
        assertEquals(false, textInput.sensitive)
    }

    @Test
    fun `Toggle has correct defaults`() {
        val toggle = SettingDescriptor.Toggle(
            key = "auto_reconnect",
            label = "Auto Reconnect",
        )

        assertEquals("auto_reconnect", toggle.key)
        assertEquals("Auto Reconnect", toggle.label)
        assertEquals("", toggle.description)
    }

    @Test
    fun `Slider validates range`() {
        val slider = SettingDescriptor.Slider(
            key = "poll_interval",
            label = "Poll Interval",
            min = 10f,
            max = 300f,
            step = 5f,
            unit = "seconds",
        )

        assertEquals("poll_interval", slider.key)
        assertEquals(10f, slider.min, 0.001f)
        assertEquals(300f, slider.max, 0.001f)
        assertEquals(5f, slider.step, 0.001f)
        assertEquals("seconds", slider.unit)
    }
}
