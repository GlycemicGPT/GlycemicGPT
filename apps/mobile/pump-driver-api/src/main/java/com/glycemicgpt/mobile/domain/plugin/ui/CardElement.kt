package com.glycemicgpt.mobile.domain.plugin.ui

/**
 * Declarative building blocks for plugin-contributed dashboard cards.
 * The platform renders these using Material 3 components.
 */
sealed class CardElement {
    data class LargeValue(
        val value: String,
        val unit: String = "",
        val color: UiColor = UiColor.DEFAULT,
    ) : CardElement()

    data class Label(
        val text: String,
        val style: LabelStyle = LabelStyle.BODY,
    ) : CardElement()

    data class StatusBadge(
        val text: String,
        val color: UiColor,
    ) : CardElement()

    data class ProgressBar(
        val value: Float,
        val max: Float,
        val label: String = "",
    ) : CardElement() {
        init {
            require(max.isFinite()) { "ProgressBar max must be finite, was $max" }
            require(value.isFinite()) { "ProgressBar value must be finite, was $value" }
            require(max > 0f) { "ProgressBar max must be positive, was $max" }
            require(value in 0f..max) { "ProgressBar value ($value) must be in 0..$max" }
        }
    }

    data class IconValue(
        val icon: PluginIcon,
        val value: String,
        val label: String = "",
    ) : CardElement()

    data class SparkLine(
        val values: List<Float>,
        val label: String = "",
    ) : CardElement() {
        init {
            require(values.isNotEmpty()) { "SparkLine values must not be empty" }
            require(values.all { it.isFinite() }) { "SparkLine values must all be finite" }
        }
    }

    data class Row(val elements: List<CardElement>) : CardElement() {
        init { require(elements.isNotEmpty()) { "Row elements must not be empty" } }
    }
    data class Column(val elements: List<CardElement>) : CardElement() {
        init { require(elements.isNotEmpty()) { "Column elements must not be empty" } }
    }
    data class Spacer(val heightDp: Int = 8) : CardElement() {
        init {
            require(heightDp >= 0) { "Spacer heightDp must be non-negative, was $heightDp" }
        }
    }
}

enum class UiColor { DEFAULT, SUCCESS, WARNING, ERROR, INFO, MUTED }

enum class LabelStyle { TITLE, SUBTITLE, BODY, CAPTION }

enum class PluginIcon {
    BLUETOOTH,
    BATTERY,
    RESERVOIR,
    INSULIN,
    GLUCOSE,
    HEART_RATE,
    SYNC,
    WARNING,
    CHECK,
    CLOCK,
    SETTINGS,
    SIGNAL,
    THERMOMETER,
}
