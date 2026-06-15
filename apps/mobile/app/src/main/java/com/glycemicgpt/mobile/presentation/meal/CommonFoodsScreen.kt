package com.glycemicgpt.mobile.presentation.meal

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.collectAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.glycemicgpt.mobile.data.meal.CarbConfidence
import com.glycemicgpt.mobile.data.meal.CommonFood
import com.glycemicgpt.mobile.presentation.detail.DetailScaffold

@Composable
fun CommonFoodsScreen(
    onBack: () -> Unit,
    viewModel: CommonFoodsViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    var reLogging by remember { mutableStateOf<CommonFood?>(null) }

    LaunchedEffect(uiState.actionError) {
        uiState.actionError?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearActionError()
        }
    }

    DetailScaffold(
        title = "Common Foods",
        onBack = onBack,
    ) { padding ->
      Box(modifier = Modifier.padding(padding).fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .testTag("common_foods_screen"),
        ) {
            when {
                uiState.disabled -> MealCenteredMessage(
                    "Meal intelligence is turned off for this server.",
                    modifier = Modifier.testTag("common_foods_disabled"),
                )
                uiState.isLoading -> MealCenteredSpinner()
                else -> {
                    VerifyBeforeDosingQualifier(modifier = Modifier.padding(16.dp))
                    uiState.errorMessage?.let { error ->
                        Text(
                            text = error,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                            modifier = Modifier.padding(horizontal = 16.dp),
                        )
                    }
                    if (uiState.items.isEmpty()) {
                        MealCenteredMessage(
                            "No common foods yet. Save a meal as a common food to build your list.",
                            modifier = Modifier.testTag("common_foods_empty"),
                        )
                    } else {
                        LazyColumn(
                            modifier = Modifier
                                .fillMaxSize()
                                .testTag("common_foods_list"),
                            contentPadding = PaddingValues(16.dp),
                            verticalArrangement = Arrangement.spacedBy(12.dp),
                        ) {
                            items(uiState.items, key = { it.id }) { food ->
                                CommonFoodItem(
                                    food = food,
                                    onReLog = { reLogging = food },
                                    onEdit = { viewModel.startEdit(food) },
                                    onDelete = { viewModel.delete(food.id) },
                                )
                            }
                        }
                    }
                }
            }
        }
        SnackbarHost(
            hostState = snackbarHostState,
            modifier = Modifier.align(Alignment.BottomCenter),
        )
      }
    }

    uiState.editing?.let { editing ->
        EditCommonFoodDialog(
            food = editing,
            isSaving = uiState.isSaving,
            error = uiState.editError,
            onSave = viewModel::saveEdit,
            onDismiss = viewModel::cancelEdit,
        )
    }

    reLogging?.let { food ->
        ReLogDialog(food = food, onDismiss = { reLogging = null })
    }
}

@Composable
private fun CommonFoodItem(
    food: CommonFood,
    onReLog: () -> Unit,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("common_food_item"),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 16.dp, top = 8.dp, bottom = 8.dp, end = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = food.name,
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    text = formatCarbRange(food.carbs),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.testTag("common_food_carbs"),
                )
            }
            FilledTonalButton(
                onClick = onReLog,
                contentPadding = PaddingValues(horizontal = 12.dp),
                modifier = Modifier.testTag("common_food_relog"),
            ) {
                Icon(
                    imageVector = Icons.Default.Refresh,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.width(4.dp))
                Text("Re-log")
            }
            IconButton(onClick = onEdit, modifier = Modifier.testTag("common_food_edit")) {
                Icon(
                    imageVector = Icons.Default.Edit,
                    contentDescription = "Edit ${food.name}",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = onDelete, modifier = Modifier.testTag("common_food_delete")) {
                Icon(
                    imageVector = Icons.Default.Delete,
                    contentDescription = "Delete ${food.name}",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/**
 * Re-log surface for v1. The API has no create-record-from-common-food path (a record needs a photo
 * upload), so this read-only sheet surfaces the saved carb range to verify, without persisting a new
 * record. Lays the seam for record creation when the backend supports it.
 */
@Composable
private fun ReLogDialog(food: CommonFood, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(food.name) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                VerifyBeforeDosingQualifier()
                CarbEstimateContent(
                    range = food.carbs,
                    confidence = CarbConfidence.UNKNOWN,
                )
                Text(
                    text = "Your saved estimate for this food. Use it to verify before dosing — " +
                        "no new photo needed.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss, modifier = Modifier.testTag("common_food_relog_close")) {
                Text("Close")
            }
        },
    )
}

@Composable
private fun EditCommonFoodDialog(
    food: CommonFood,
    isSaving: Boolean,
    error: String?,
    onSave: (name: String, low: String, high: String) -> Unit,
    onDismiss: () -> Unit,
) {
    // Key on the food id so the fields re-initialize if the dialog is reused for a different food.
    var name by remember(food.id) { mutableStateOf(food.name) }
    var lowText by remember(food.id) { mutableStateOf(formatEditableGrams(food.carbs.lowGrams)) }
    var highText by remember(food.id) { mutableStateOf(formatEditableGrams(food.carbs.highGrams)) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Edit common food") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text("Name") },
                    singleLine = true,
                    modifier = Modifier
                        .fillMaxWidth()
                        .testTag("common_food_edit_name"),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    OutlinedTextField(
                        value = lowText,
                        onValueChange = { lowText = it },
                        label = { Text("Low (g)") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier
                            .weight(1f)
                            .testTag("common_food_edit_low"),
                    )
                    OutlinedTextField(
                        value = highText,
                        onValueChange = { highText = it },
                        label = { Text("High (g)") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier
                            .weight(1f)
                            .testTag("common_food_edit_high"),
                    )
                }
                if (error != null) {
                    Text(
                        text = error,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        },
        confirmButton = {
            Button(
                onClick = { onSave(name, lowText, highText) },
                enabled = !isSaving,
                modifier = Modifier.testTag("common_food_edit_save"),
            ) { Text(if (isSaving) "Saving…" else "Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

