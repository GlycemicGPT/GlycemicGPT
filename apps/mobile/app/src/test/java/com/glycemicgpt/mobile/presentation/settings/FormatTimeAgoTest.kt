package com.glycemicgpt.mobile.presentation.settings

import org.junit.Assert.assertEquals
import org.junit.Test

class FormatTimeAgoTest {

    @Test
    fun `returns just now for timestamps less than 60 seconds ago`() {
        val now = System.currentTimeMillis()
        assertEquals("just now", formatTimeAgo(now - 30_000))
    }

    @Test
    fun `returns minutes ago for timestamps 1-59 minutes ago`() {
        val now = System.currentTimeMillis()
        val result = formatTimeAgo(now - 5 * 60_000)
        assertEquals("5m ago", result)
    }

    @Test
    fun `returns hours ago for timestamps 1-23 hours ago`() {
        val now = System.currentTimeMillis()
        val result = formatTimeAgo(now - 3 * 3_600_000)
        assertEquals("3h ago", result)
    }

    @Test
    fun `returns days ago for timestamps over 24 hours ago`() {
        val now = System.currentTimeMillis()
        val result = formatTimeAgo(now - 2L * 86_400_000)
        assertEquals("2d ago", result)
    }

    @Test
    fun `returns just now for future timestamps (clock skew)`() {
        val future = System.currentTimeMillis() + 60_000
        assertEquals("just now", formatTimeAgo(future))
    }
}
