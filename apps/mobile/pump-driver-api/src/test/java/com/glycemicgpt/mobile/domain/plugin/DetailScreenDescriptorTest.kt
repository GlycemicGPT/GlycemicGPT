package com.glycemicgpt.mobile.domain.plugin

import com.glycemicgpt.mobile.domain.plugin.ui.ButtonStyle
import com.glycemicgpt.mobile.domain.plugin.ui.CardElement
import com.glycemicgpt.mobile.domain.plugin.ui.DetailElement
import com.glycemicgpt.mobile.domain.plugin.ui.DetailScreenDescriptor
import com.glycemicgpt.mobile.domain.plugin.ui.LabelStyle
import com.glycemicgpt.mobile.domain.plugin.ui.SettingDescriptor
import org.junit.Assert.assertEquals
import org.junit.Test

class DetailScreenDescriptorTest {

    @Test(expected = IllegalArgumentException::class)
    fun `blank title is rejected`() {
        DetailScreenDescriptor(
            title = "",
            elements = emptyList(),
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun `whitespace-only title is rejected`() {
        DetailScreenDescriptor(
            title = "   ",
            elements = emptyList(),
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun `duplicate interactive keys are rejected`() {
        DetailScreenDescriptor(
            title = "Test Detail",
            elements = listOf(
                DetailElement.Interactive(
                    SettingDescriptor.Toggle(key = "toggle_a", label = "Toggle A"),
                ),
                DetailElement.Interactive(
                    SettingDescriptor.Toggle(key = "toggle_a", label = "Toggle A duplicate"),
                ),
            ),
        )
    }

    @Test
    fun `valid mixed elements are accepted`() {
        val descriptor = DetailScreenDescriptor(
            title = "Test Detail",
            elements = listOf(
                DetailElement.SectionHeader("Section 1"),
                DetailElement.Display(
                    CardElement.Label(text = "Status: OK", style = LabelStyle.BODY),
                ),
                DetailElement.Interactive(
                    SettingDescriptor.Toggle(key = "toggle_a", label = "Toggle A"),
                ),
                DetailElement.Interactive(
                    SettingDescriptor.ActionButton(
                        key = "action_b",
                        label = "Do Action",
                        style = ButtonStyle.PRIMARY,
                    ),
                ),
                DetailElement.SectionHeader("Section 2"),
                DetailElement.Display(CardElement.SparkLine(values = listOf(1f, 2f, 3f))),
            ),
        )
        assertEquals("Test Detail", descriptor.title)
        assertEquals(6, descriptor.elements.size)
    }

    @Test
    fun `display-only elements do not cause key conflicts`() {
        // Display elements have no keys, so multiple should be fine
        val descriptor = DetailScreenDescriptor(
            title = "Display Only",
            elements = listOf(
                DetailElement.Display(CardElement.Label(text = "A")),
                DetailElement.Display(CardElement.Label(text = "B")),
                DetailElement.Display(CardElement.Label(text = "C")),
            ),
        )
        assertEquals(3, descriptor.elements.size)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `blank section header title is rejected`() {
        DetailElement.SectionHeader("")
    }

    @Test
    fun `empty elements list is valid`() {
        val descriptor = DetailScreenDescriptor(
            title = "Empty Detail",
            elements = emptyList(),
        )
        assertEquals("Empty Detail", descriptor.title)
        assertEquals(0, descriptor.elements.size)
    }

    @Test
    fun `exactly MAX_ELEMENTS is accepted`() {
        val elements = (1..DetailScreenDescriptor.MAX_ELEMENTS).map {
            DetailElement.Display(CardElement.Label(text = "Item $it"))
        }
        val descriptor = DetailScreenDescriptor(
            title = "Max Elements",
            elements = elements,
        )
        assertEquals(DetailScreenDescriptor.MAX_ELEMENTS, descriptor.elements.size)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `MAX_ELEMENTS plus one is rejected`() {
        val elements = (1..DetailScreenDescriptor.MAX_ELEMENTS + 1).map {
            DetailElement.Display(CardElement.Label(text = "Item $it"))
        }
        DetailScreenDescriptor(
            title = "Over Max",
            elements = elements,
        )
    }
}
