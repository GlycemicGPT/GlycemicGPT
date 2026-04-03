package com.glycemicgpt.mobile.domain.plugin.ui

/**
 * Describes a full-screen detail view for a plugin dashboard card.
 * Returned from [Plugin.observeDetailScreen] when the user taps a card
 * with [DashboardCardDescriptor.hasDetail] set to true.
 *
 * The detail screen renders a scrollable list of [DetailElement] items.
 * Elements are polymorphic: display-only elements reuse [CardElement],
 * interactive elements reuse [SettingDescriptor], and section headers
 * provide visual grouping.
 */
data class DetailScreenDescriptor(
    val title: String,
    val elements: List<DetailElement>,
) {
    init {
        require(title.isNotBlank()) { "DetailScreenDescriptor title must not be blank" }
        require(elements.size <= MAX_ELEMENTS) {
            "DetailScreenDescriptor has ${elements.size} elements, max is $MAX_ELEMENTS"
        }

        // Validate no duplicate keys among interactive elements
        val interactiveKeys = elements
            .filterIsInstance<DetailElement.Interactive>()
            .map { it.setting.key }
        require(interactiveKeys.size == interactiveKeys.distinct().size) {
            val dupes = interactiveKeys.groupBy { it }.filter { it.value.size > 1 }.keys
            "DetailScreenDescriptor contains duplicate interactive keys: $dupes"
        }
    }

    companion object {
        /** Maximum number of elements per detail screen to prevent UI DoS. */
        const val MAX_ELEMENTS = 100
    }
}

/**
 * A single element in a plugin detail screen.
 *
 * Wraps existing SDK types rather than duplicating them:
 * - [Display] renders a [CardElement] (read-only)
 * - [Interactive] renders a [SettingDescriptor] (editable, triggers actions)
 * - [SectionHeader] provides visual grouping with a styled title
 */
sealed class DetailElement {
    /** A display-only element rendered using the card element renderer. */
    data class Display(val element: CardElement) : DetailElement()

    /** An interactive element rendered using the settings renderer. */
    data class Interactive(val setting: SettingDescriptor) : DetailElement()

    /** A section header for visual grouping within the detail screen. */
    data class SectionHeader(val title: String) : DetailElement() {
        init {
            require(title.isNotBlank()) { "SectionHeader title must not be blank" }
        }
    }
}
