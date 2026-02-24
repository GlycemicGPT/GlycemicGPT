package com.glycemicgpt.mobile.domain.plugin.ui

/**
 * Declarative description of a single plugin setting field.
 * The platform renders these using Material 3 components in the settings screen.
 */
sealed class SettingDescriptor {
    abstract val key: String

    companion object {
        private val VALID_KEY = Regex("^[a-zA-Z][a-zA-Z0-9_.-]{0,127}$")
        internal fun requireValidKey(key: String) {
            require(VALID_KEY.matches(key)) {
                "Setting key must match $VALID_KEY, was '$key'"
            }
        }
    }

    data class TextInput(
        override val key: String,
        val label: String,
        val hint: String = "",
        /** If true, the field is masked in the UI (password-style). */
        val sensitive: Boolean = false,
    ) : SettingDescriptor() {
        init { requireValidKey(key) }
    }

    data class Toggle(
        override val key: String,
        val label: String,
        val description: String = "",
    ) : SettingDescriptor() {
        init { requireValidKey(key) }
    }

    data class Slider(
        override val key: String,
        val label: String,
        val min: Float,
        val max: Float,
        val step: Float = 1f,
        val unit: String = "",
    ) : SettingDescriptor() {
        init {
            requireValidKey(key)
            require(min < max) { "Slider min ($min) must be less than max ($max)" }
            require(step > 0) { "Slider step must be positive, was $step" }
            require(step <= max - min) { "Slider step ($step) must not exceed range (${max - min})" }
        }
    }

    data class Dropdown(
        override val key: String,
        val label: String,
        val options: List<DropdownOption>,
    ) : SettingDescriptor() {
        init {
            requireValidKey(key)
            require(options.isNotEmpty()) { "Dropdown options must not be empty for key '$key'" }
        }
    }

    data class ActionButton(
        override val key: String,
        val label: String,
        val style: ButtonStyle = ButtonStyle.DEFAULT,
    ) : SettingDescriptor() {
        init { requireValidKey(key) }
    }

    data class InfoText(
        override val key: String,
        val text: String,
    ) : SettingDescriptor() {
        init { requireValidKey(key) }
    }
}

data class DropdownOption(val value: String, val label: String) {
    init {
        require(value.isNotBlank()) { "DropdownOption value must not be blank" }
    }
}

enum class ButtonStyle { DEFAULT, PRIMARY, DESTRUCTIVE }

/**
 * A named section of plugin settings, rendered as a group with a header.
 */
data class PluginSettingsSection(
    val title: String,
    val items: List<SettingDescriptor>,
)

/**
 * Complete settings descriptor for a plugin, composed of sections.
 */
data class PluginSettingsDescriptor(
    val sections: List<PluginSettingsSection>,
) {
    init {
        val allKeys = sections.flatMap { it.items }.map { it.key }
        require(allKeys.size == allKeys.distinct().size) {
            val dupes = allKeys.groupBy { it }.filter { it.value.size > 1 }.keys
            "PluginSettingsDescriptor contains duplicate setting keys: $dupes"
        }
    }
}
