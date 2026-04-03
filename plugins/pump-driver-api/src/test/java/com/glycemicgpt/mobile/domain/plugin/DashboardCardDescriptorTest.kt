package com.glycemicgpt.mobile.domain.plugin

import com.glycemicgpt.mobile.domain.plugin.ui.DashboardCardDescriptor
import org.junit.Assert.assertEquals
import org.junit.Test

class DashboardCardDescriptorTest {

    @Test
    fun `default priority is 100`() {
        val card = DashboardCardDescriptor(
            id = "test_card",
            title = "Test Card",
            elements = emptyList(),
        )

        assertEquals(100, card.priority)
    }

    @Test
    fun `cards sort by priority`() {
        val highPriority = DashboardCardDescriptor(
            id = "high",
            title = "High Priority",
            priority = 10,
            elements = emptyList(),
        )
        val defaultPriority = DashboardCardDescriptor(
            id = "default",
            title = "Default Priority",
            elements = emptyList(),
        )
        val lowPriority = DashboardCardDescriptor(
            id = "low",
            title = "Low Priority",
            priority = 200,
            elements = emptyList(),
        )

        val sorted = listOf(lowPriority, defaultPriority, highPriority).sortedBy { it.priority }

        assertEquals("high", sorted[0].id)
        assertEquals("default", sorted[1].id)
        assertEquals("low", sorted[2].id)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `blank id is rejected`() {
        DashboardCardDescriptor(
            id = "",
            title = "No ID",
            elements = emptyList(),
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun `blank title is rejected`() {
        DashboardCardDescriptor(
            id = "valid_id",
            title = "",
            elements = emptyList(),
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun `whitespace-only id is rejected`() {
        DashboardCardDescriptor(
            id = "   ",
            title = "Valid Title",
            elements = emptyList(),
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun `whitespace-only title is rejected`() {
        DashboardCardDescriptor(
            id = "valid_id",
            title = "   ",
            elements = emptyList(),
        )
    }

    @Test
    fun `hasDetail defaults to false`() {
        val card = DashboardCardDescriptor(
            id = "test",
            title = "Test",
            elements = emptyList(),
        )
        assertEquals(false, card.hasDetail)
    }

    @Test
    fun `hasDetail can be set to true`() {
        val card = DashboardCardDescriptor(
            id = "test",
            title = "Test",
            elements = emptyList(),
            hasDetail = true,
        )
        assertEquals(true, card.hasDetail)
    }
}
