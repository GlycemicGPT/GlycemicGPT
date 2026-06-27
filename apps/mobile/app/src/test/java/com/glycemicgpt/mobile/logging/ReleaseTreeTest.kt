package com.glycemicgpt.mobile.logging

import com.glycemicgpt.mobile.domain.format.GlucoseFormat
import com.glycemicgpt.mobile.domain.model.GlucoseUnit
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ReleaseTreeTest {

    @Test
    fun `scrubs JWT tokens from messages`() {
        // Fake three-part dot-separated string matching JWT structure (not a real token)
        val msg = "Token: aaaaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbb.cccccccccccccccccccccccc"
        val result = ReleaseTree.scrubSensitiveData(msg)
        assertEquals("Token: [TOKEN]", result)
    }

    @Test
    fun `scrubs email addresses`() {
        val msg = "User logged in: patient@example.com"
        val result = ReleaseTree.scrubSensitiveData(msg)
        assertEquals("User logged in: [EMAIL]", result)
    }

    @Test
    fun `scrubs blood glucose values`() {
        val msg = "Current reading: 250 mg/dL"
        val result = ReleaseTree.scrubSensitiveData(msg)
        assertEquals("Current reading: [BG]", result)
    }

    @Test
    fun `scrubs BG value without space before unit`() {
        val msg = "Reading: 85mg/dL"
        val result = ReleaseTree.scrubSensitiveData(msg)
        assertEquals("Reading: [BG]", result)
    }

    @Test
    fun `scrubs mmol per L values`() {
        val msg = "Reading: 5.4 mmol/L"
        val result = ReleaseTree.scrubSensitiveData(msg)
        assertEquals("Reading: [BG]", result)
    }

    @Test
    fun `scrubs mmol values produced by the glucose formatter`() {
        // The mmol format chosen for display must still match BG_MMOL_PATTERN so it cannot
        // bypass the release log scrubber (AC: log scrubber still works).
        for (mgDl in listOf(70, 100, 120, 180, 250)) {
            val rendered = GlucoseFormat.formatWithLabel(mgDl, GlucoseUnit.MMOL)
            val msg = "Current reading: $rendered"
            assertEquals(
                "mmol output '$rendered' should be scrubbed",
                "Current reading: [BG]",
                ReleaseTree.scrubSensitiveData(msg),
            )
        }
    }

    @Test
    fun `preserves non-sensitive messages`() {
        val msg = "Connection test failed: timeout"
        val result = ReleaseTree.scrubSensitiveData(msg)
        assertEquals("Connection test failed: timeout", result)
    }

    @Test
    fun `scrubs multiple sensitive values in one message`() {
        val msg = "Alert for user@test.com: 320 mg/dL"
        val result = ReleaseTree.scrubSensitiveData(msg)
        assertFalse(result.contains("user@test.com"))
        assertFalse(result.contains("320"))
        assertTrue(result.contains("[EMAIL]"))
        assertTrue(result.contains("[BG]"))
    }
}
