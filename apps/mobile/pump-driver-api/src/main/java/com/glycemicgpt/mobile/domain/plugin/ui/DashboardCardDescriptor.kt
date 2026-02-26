package com.glycemicgpt.mobile.domain.plugin.ui

/**
 * Declarative description of a dashboard card contributed by a plugin.
 * The platform renders these below the core cards using Material 3.
 *
 * @property priority Lower values appear higher on the dashboard.
 */
data class DashboardCardDescriptor(
    val id: String,
    val title: String,
    val priority: Int = 100,
    val elements: List<CardElement>,
    /** When true, the platform renders this card as tappable with a chevron indicator. */
    val hasDetail: Boolean = false,
) {
    init {
        require(id.isNotBlank()) { "DashboardCardDescriptor id must not be blank" }
        require(title.isNotBlank()) { "DashboardCardDescriptor title must not be blank" }
    }
}
