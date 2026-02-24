package com.glycemicgpt.mobile.presentation.plugin

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import com.glycemicgpt.mobile.domain.plugin.PluginSettingsStore
import com.glycemicgpt.mobile.domain.plugin.ui.ButtonStyle
import com.glycemicgpt.mobile.domain.plugin.ui.PluginSettingsDescriptor
import com.glycemicgpt.mobile.domain.plugin.ui.SettingDescriptor
import kotlin.math.roundToInt

/**
 * Renders a [PluginSettingsDescriptor] as Material 3 UI components.
 * Reads/writes values through the plugin's [PluginSettingsStore].
 */
@Composable
fun PluginSettingsRenderer(
    descriptor: PluginSettingsDescriptor,
    settingsStore: PluginSettingsStore,
    onAction: (key: String) -> Unit = {},
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        descriptor.sections.forEachIndexed { index, section ->
            if (index > 0) {
                Spacer(modifier = Modifier.height(16.dp))
            }
            Text(
                text = section.title,
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.padding(bottom = 8.dp),
            )
            section.items.forEach { item ->
                SettingItem(item, settingsStore, onAction)
                Spacer(modifier = Modifier.height(8.dp))
            }
        }
    }
}

@Composable
private fun SettingItem(
    descriptor: SettingDescriptor,
    store: PluginSettingsStore,
    onAction: (String) -> Unit,
) {
    when (descriptor) {
        is SettingDescriptor.TextInput -> TextInputSetting(descriptor, store)
        is SettingDescriptor.Toggle -> ToggleSetting(descriptor, store)
        is SettingDescriptor.Slider -> SliderSetting(descriptor, store)
        is SettingDescriptor.Dropdown -> DropdownSetting(descriptor, store)
        is SettingDescriptor.ActionButton -> ActionButtonSetting(descriptor, onAction)
        is SettingDescriptor.InfoText -> InfoTextSetting(descriptor)
    }
}

@Composable
private fun TextInputSetting(descriptor: SettingDescriptor.TextInput, store: PluginSettingsStore) {
    var value by remember { mutableStateOf(store.getString(descriptor.key)) }
    OutlinedTextField(
        value = value,
        onValueChange = { value = it },
        label = { Text(descriptor.label) },
        placeholder = if (descriptor.hint.isNotEmpty()) {
            { Text(descriptor.hint) }
        } else {
            null
        },
        visualTransformation = if (descriptor.sensitive) {
            PasswordVisualTransformation()
        } else {
            VisualTransformation.None
        },
        singleLine = true,
        modifier = Modifier
            .fillMaxWidth()
            .onFocusChanged { if (!it.isFocused) store.putString(descriptor.key, value) },
    )
}

@Composable
private fun ToggleSetting(descriptor: SettingDescriptor.Toggle, store: PluginSettingsStore) {
    var checked by remember { mutableStateOf(store.getBoolean(descriptor.key)) }
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = descriptor.label,
                style = MaterialTheme.typography.bodyMedium,
            )
            if (descriptor.description.isNotEmpty()) {
                Text(
                    text = descriptor.description,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        Spacer(modifier = Modifier.width(8.dp))
        Switch(
            checked = checked,
            onCheckedChange = {
                checked = it
                store.putBoolean(descriptor.key, it)
            },
        )
    }
}

@Composable
private fun SliderSetting(descriptor: SettingDescriptor.Slider, store: PluginSettingsStore) {
    var value by remember {
        mutableFloatStateOf(
            store.getFloat(descriptor.key, descriptor.min)
                .coerceIn(descriptor.min, descriptor.max),
        )
    }
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = descriptor.label,
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.weight(1f),
            )
            val displayValue = if (descriptor.step >= 1f) {
                "${value.roundToInt()}"
            } else {
                "%.1f".format(value)
            }
            Text(
                text = "$displayValue ${descriptor.unit}".trim(),
                style = MaterialTheme.typography.bodyMedium,
            )
        }
        val steps = if (descriptor.step > 0) {
            ((descriptor.max - descriptor.min) / descriptor.step).toInt() - 1
        } else {
            0
        }
        Slider(
            value = value,
            onValueChange = { value = it },
            onValueChangeFinished = {
                store.putFloat(descriptor.key, value.coerceIn(descriptor.min, descriptor.max))
            },
            valueRange = descriptor.min..descriptor.max,
            steps = steps.coerceAtLeast(0),
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DropdownSetting(descriptor: SettingDescriptor.Dropdown, store: PluginSettingsStore) {
    var expanded by remember { mutableStateOf(false) }
    val currentValue = store.getString(descriptor.key)
    val currentLabel = descriptor.options.find { it.value == currentValue }?.label
        ?: descriptor.options.firstOrNull()?.label ?: ""

    ExposedDropdownMenuBox(
        expanded = expanded,
        onExpandedChange = { expanded = it },
    ) {
        OutlinedTextField(
            value = currentLabel,
            onValueChange = {},
            readOnly = true,
            label = { Text(descriptor.label) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) },
            modifier = Modifier
                .fillMaxWidth()
                .menuAnchor(MenuAnchorType.PrimaryNotEditable),
        )
        ExposedDropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false },
        ) {
            descriptor.options.forEach { option ->
                DropdownMenuItem(
                    text = { Text(option.label) },
                    onClick = {
                        store.putString(descriptor.key, option.value)
                        expanded = false
                    },
                )
            }
        }
    }
}

@Composable
private fun ActionButtonSetting(descriptor: SettingDescriptor.ActionButton, onAction: (String) -> Unit) {
    when (descriptor.style) {
        ButtonStyle.PRIMARY -> Button(
            onClick = { onAction(descriptor.key) },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(descriptor.label)
        }
        ButtonStyle.DESTRUCTIVE -> OutlinedButton(
            onClick = { onAction(descriptor.key) },
            colors = ButtonDefaults.outlinedButtonColors(
                contentColor = MaterialTheme.colorScheme.error,
            ),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(descriptor.label)
        }
        ButtonStyle.DEFAULT -> OutlinedButton(
            onClick = { onAction(descriptor.key) },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(descriptor.label)
        }
    }
}

@Composable
private fun InfoTextSetting(descriptor: SettingDescriptor.InfoText) {
    Text(
        text = descriptor.text,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}
