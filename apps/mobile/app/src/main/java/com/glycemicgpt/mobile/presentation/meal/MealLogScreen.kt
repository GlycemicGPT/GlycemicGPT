package com.glycemicgpt.mobile.presentation.meal

import android.Manifest
import android.content.ContentResolver
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.LocalCafe
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Restaurant
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.collectAsState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.hilt.navigation.compose.hiltViewModel
import com.glycemicgpt.mobile.data.meal.FoodRecord
import com.glycemicgpt.mobile.data.meal.MealPhotoFiles
import com.glycemicgpt.mobile.presentation.detail.DetailScaffold
import androidx.compose.foundation.shape.RoundedCornerShape
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlin.math.max

@Composable
fun MealLogScreen(
    onBack: () -> Unit,
    onNavigateToHistory: () -> Unit,
    onNavigateToCommonFoods: () -> Unit,
    viewModel: MealLogViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    val context = LocalContext.current

    // rememberSaveable so a rotation while the camera app is open doesn't lose the capture URI.
    var pendingCaptureUri by rememberSaveable { mutableStateOf<Uri?>(null) }
    var cameraPermissionDenied by remember { mutableStateOf(false) }

    val galleryLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.PickVisualMedia(),
    ) { uri: Uri? -> uri?.let { viewModel.onImagePicked(it) } }

    val cameraLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.TakePicture(),
    ) { success: Boolean ->
        val uri = pendingCaptureUri
        if (success && uri != null) {
            viewModel.onImagePicked(uri)
        } else if (uri != null) {
            // Capture cancelled: drop just this empty temp file so it doesn't linger in the cache.
            MealPhotoFiles.deleteCapture(context, uri)
        }
        pendingCaptureUri = null
    }

    fun launchCamera() {
        cameraPermissionDenied = false
        val uri = MealPhotoFiles.createCaptureUri(context)
        pendingCaptureUri = uri
        cameraLauncher.launch(uri)
    }

    val cameraPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted: Boolean ->
        if (granted) launchCamera() else cameraPermissionDenied = true
    }

    fun onTakePhoto() {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
        ) {
            launchCamera()
        } else {
            cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    fun onChooseFromGallery() {
        galleryLauncher.launch(
            PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly),
        )
    }

    DetailScaffold(title = "Log a Meal", onBack = onBack) { padding ->
        Box(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize()
                .testTag("meal_log_screen"),
        ) {
            when (uiState.pageState) {
                MealLogPageState.Loading -> MealCenteredSpinner("Loading…")
                MealLogPageState.Disabled -> MealUnavailableMessage(
                    title = "Meal logging isn't turned on",
                    body = "Meal intelligence is turned off for this server. " +
                        "Ask your server admin to enable it to estimate carbs from a photo.",
                    tag = "meal_feature_disabled",
                )
                MealLogPageState.Offline -> OfflineRetry(onRetry = viewModel::checkAvailability)
                MealLogPageState.Ready -> ReadyContent(
                    uiState = uiState,
                    cameraPermissionDenied = cameraPermissionDenied,
                    onTakePhoto = ::onTakePhoto,
                    onChooseFromGallery = ::onChooseFromGallery,
                    onNavigateToHistory = onNavigateToHistory,
                    onNavigateToCommonFoods = onNavigateToCommonFoods,
                    onStartCorrection = viewModel::startCorrection,
                    onCancelCorrection = viewModel::cancelCorrection,
                    onSubmitCorrection = viewModel::submitCorrection,
                    onSaveAsCommonFood = viewModel::saveAsCommonFood,
                    onStartIdentityEdit = viewModel::startIdentityEdit,
                    onCancelIdentityEdit = viewModel::cancelIdentityEdit,
                    onConfirmIdentity = viewModel::confirmIdentity,
                    onLoadAudit = viewModel::loadAudit,
                    onHideAudit = viewModel::hideAudit,
                    onReset = viewModel::reset,
                    onClearError = viewModel::clearError,
                )
            }
        }
    }
}

@Composable
private fun ReadyContent(
    uiState: MealLogUiState,
    cameraPermissionDenied: Boolean,
    onTakePhoto: () -> Unit,
    onChooseFromGallery: () -> Unit,
    onNavigateToHistory: () -> Unit,
    onNavigateToCommonFoods: () -> Unit,
    onStartCorrection: () -> Unit,
    onCancelCorrection: () -> Unit,
    onSubmitCorrection: (String, String) -> Unit,
    onSaveAsCommonFood: (String) -> Unit,
    onStartIdentityEdit: () -> Unit,
    onCancelIdentityEdit: () -> Unit,
    onConfirmIdentity: (String) -> Unit,
    onLoadAudit: () -> Unit,
    onHideAudit: () -> Unit,
    onReset: () -> Unit,
    onClearError: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        // Pinned above the scroll region so the safety qualifier is ALWAYS visible on the result
        // surface, no matter how long the content below grows.
        VerifyBeforeDosingQualifier()

        Column(
            modifier = Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            when {
                uiState.isUploading -> MealCenteredSpinner(
                    message = "Estimating carbs…",
                    modifier = Modifier.testTag("meal_uploading"),
                )

                uiState.unavailableReason != null ->
                    UnavailableContent(reason = uiState.unavailableReason, onBack = onReset)

                uiState.record != null -> ResultContent(
                    record = uiState.record,
                    uiState = uiState,
                    onStartCorrection = onStartCorrection,
                    onCancelCorrection = onCancelCorrection,
                    onSubmitCorrection = onSubmitCorrection,
                    onSaveAsCommonFood = onSaveAsCommonFood,
                    onStartIdentityEdit = onStartIdentityEdit,
                    onCancelIdentityEdit = onCancelIdentityEdit,
                    onConfirmIdentity = onConfirmIdentity,
                    onLoadAudit = onLoadAudit,
                    onHideAudit = onHideAudit,
                    onReset = onReset,
                )

                else -> IdleContent(
                    cameraPermissionDenied = cameraPermissionDenied,
                    onTakePhoto = onTakePhoto,
                    onChooseFromGallery = onChooseFromGallery,
                    onNavigateToHistory = onNavigateToHistory,
                    onNavigateToCommonFoods = onNavigateToCommonFoods,
                )
            }

            if (uiState.errorMessage != null) {
                ErrorBanner(message = uiState.errorMessage, onDismiss = onClearError)
            }
        }
    }
}

@Composable
private fun IdleContent(
    cameraPermissionDenied: Boolean,
    onTakePhoto: () -> Unit,
    onChooseFromGallery: () -> Unit,
    onNavigateToHistory: () -> Unit,
    onNavigateToCommonFoods: () -> Unit,
) {
    Text(
        text = "Snap a photo of your meal to get an estimated carb range you can correct and save.",
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Button(
        onClick = onTakePhoto,
        modifier = Modifier
            .fillMaxWidth()
            .testTag("meal_capture_camera"),
    ) {
        Icon(Icons.Default.PhotoCamera, contentDescription = null, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(8.dp))
        Text("Take photo")
    }
    OutlinedButton(
        onClick = onChooseFromGallery,
        modifier = Modifier
            .fillMaxWidth()
            .testTag("meal_capture_gallery"),
    ) {
        Icon(Icons.Default.PhotoLibrary, contentDescription = null, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(8.dp))
        Text("Choose from gallery")
    }
    if (cameraPermissionDenied) {
        Text(
            text = "Camera permission is needed to take a photo. You can still choose one from your gallery.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.error,
            modifier = Modifier.testTag("meal_camera_permission_denied"),
        )
    }

    // No-photo path: re-log a saved common food.
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 4.dp)) {
        HorizontalDivider(modifier = Modifier.weight(1f))
        Text(
            text = "OR",
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 12.dp),
        )
        HorizontalDivider(modifier = Modifier.weight(1f))
    }
    FilledTonalButton(
        onClick = onNavigateToCommonFoods,
        modifier = Modifier
            .fillMaxWidth()
            .testTag("meal_relog_common"),
    ) {
        Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(8.dp))
        Text("Re-log a common food")
    }

    Spacer(Modifier.height(8.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
        OutlinedButton(
            onClick = onNavigateToHistory,
            modifier = Modifier
                .weight(1f)
                .testTag("meal_history_button"),
        ) {
            Icon(Icons.Default.History, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text("History")
        }
        OutlinedButton(
            onClick = onNavigateToCommonFoods,
            modifier = Modifier
                .weight(1f)
                .testTag("common_foods_button"),
        ) {
            Icon(Icons.Default.Restaurant, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text("Common foods")
        }
    }
}

@Composable
private fun ResultContent(
    record: FoodRecord,
    uiState: MealLogUiState,
    onStartCorrection: () -> Unit,
    onCancelCorrection: () -> Unit,
    onSubmitCorrection: (String, String) -> Unit,
    onSaveAsCommonFood: (String) -> Unit,
    onStartIdentityEdit: () -> Unit,
    onCancelIdentityEdit: () -> Unit,
    onConfirmIdentity: (String) -> Unit,
    onLoadAudit: () -> Unit,
    onHideAudit: () -> Unit,
    onReset: () -> Unit,
) {
    var showSaveDialog by remember { mutableStateOf(false) }

    uiState.photoUri?.let { MealPhotoThumbnail(uri = it) }

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("meal_result_card"),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            // Food identity is a first-class, confirmable thing (Story 50.H2) --
            // distinct from carb correction. Grounding only applies once it's
            // confirmed, so a confident misidentification isn't certified.
            MealIdentitySection(
                record = record,
                uiState = uiState,
                onStartEdit = onStartIdentityEdit,
                onCancelEdit = onCancelIdentityEdit,
                onConfirm = onConfirmIdentity,
            )
            CarbEstimateContent(
                range = record.displayRange,
                confidence = record.confidence,
                isCorrected = record.isCorrected,
                originalRange = record.estimate,
                // Only the fresh-estimate surface carries dispersion (transient on create).
                dispersion = record.dispersion,
            )
            Text(
                text = formatMealTimestamp(record.mealTimestamp),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }

    if (uiState.isCorrecting) {
        CorrectionEditor(
            initialLow = record.displayRange.lowGrams,
            initialHigh = record.displayRange.highGrams,
            isSaving = uiState.isSavingCorrection,
            error = uiState.correctionError,
            onSubmit = onSubmitCorrection,
            onCancel = onCancelCorrection,
        )
    } else {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
            OutlinedButton(
                onClick = onStartCorrection,
                modifier = Modifier
                    .weight(1f)
                    .testTag("meal_correct_button"),
            ) { Text("Correct") }
            Button(
                onClick = { showSaveDialog = true },
                enabled = !uiState.isSavingCommonFood,
                modifier = Modifier
                    .weight(1f)
                    .testTag("meal_save_common_button"),
            ) { Text("Save as common food") }
        }
    }

    if (uiState.savedCommonFoodName != null) {
        Text(
            text = "Saved \"${uiState.savedCommonFoodName}\" to your common foods.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.primary,
            modifier = Modifier.testTag("meal_saved_common_confirmation"),
        )
    }

    // "How was this estimated" provenance (Story 50.H3) -- on demand, descriptive.
    MealAuditSection(
        uiState = uiState,
        onLoad = onLoadAudit,
        onHide = onHideAudit,
    )

    TextButton(
        onClick = onReset,
        modifier = Modifier
            .fillMaxWidth()
            .testTag("meal_log_another"),
    ) { Text("Log another meal") }

    if (showSaveDialog) {
        SaveAsCommonFoodDialog(
            isSaving = uiState.isSavingCommonFood,
            onConfirm = { name ->
                onSaveAsCommonFood(name)
                showSaveDialog = false
            },
            onDismiss = { showSaveDialog = false },
        )
    }
}

@Composable
private fun CorrectionEditor(
    initialLow: Double,
    initialHigh: Double,
    isSaving: Boolean,
    error: String?,
    onSubmit: (String, String) -> Unit,
    onCancel: () -> Unit,
) {
    // Key on the seed values so the fields reset if the editor reopens for a different estimate.
    var lowText by remember(initialLow, initialHigh) { mutableStateOf(formatEditableGrams(initialLow)) }
    var highText by remember(initialLow, initialHigh) { mutableStateOf(formatEditableGrams(initialHigh)) }

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("meal_correction_editor"),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                text = "Correct the carb estimate (grams)",
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurface,
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
                        .testTag("meal_correct_low_input"),
                )
                OutlinedTextField(
                    value = highText,
                    onValueChange = { highText = it },
                    label = { Text("High (g)") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier
                        .weight(1f)
                        .testTag("meal_correct_high_input"),
                )
            }
            if (error != null) {
                Text(
                    text = error,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
                OutlinedButton(
                    onClick = onCancel,
                    enabled = !isSaving,
                    modifier = Modifier.weight(1f),
                ) { Text("Cancel") }
                Button(
                    onClick = { onSubmit(lowText, highText) },
                    enabled = !isSaving,
                    modifier = Modifier
                        .weight(1f)
                        .testTag("meal_correct_save"),
                ) { Text(if (isSaving) "Saving…" else "Save") }
            }
        }
    }
}

/**
 * Food-identity confirmation (Story 50.H2). The AI's guess is shown as a
 * confirmable thing -- distinct from carb correction. Confirming opens the
 * grounding gate server-side; an own-history match pre-fills a one-tap confirm,
 * and a sample-level identity disagreement is surfaced as the reason to confirm.
 */
@Composable
private fun MealIdentitySection(
    record: FoodRecord,
    uiState: MealLogUiState,
    onStartEdit: () -> Unit,
    onCancelEdit: () -> Unit,
    onConfirm: (String) -> Unit,
) {
    if (uiState.isEditingIdentity) {
        IdentityEditor(
            initial = record.displayIdentity.orEmpty(),
            isSaving = uiState.isSavingIdentity,
            error = uiState.identityError,
            onConfirm = onConfirm,
            onCancel = onCancelEdit,
        )
        return
    }

    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(
            text = record.displayIdentity ?: "Unidentified food",
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.testTag("meal_identity"),
        )
        if (record.identityConfirmed) {
            Text(
                text = "✓ You confirmed this food.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.testTag("meal_identity_confirmed"),
            )
            TextButton(
                onClick = onStartEdit,
                modifier = Modifier.testTag("meal_identity_edit"),
            ) { Text("Change what this is") }
        } else {
            val disagreed = record.dispersion?.identityAgreement == false
            Text(
                text = when {
                    disagreed ->
                        "The AI wasn't sure what this is. Confirm it so we can look " +
                            "up its nutrition."
                    record.suggestedIdentity != null ->
                        "Looks like your saved \"${record.suggestedIdentity}\" -- confirm?"
                    else ->
                        "Confirm what this food is so we can ground it against real " +
                            "nutrition data."
                },
                style = MaterialTheme.typography.bodySmall,
                color = if (disagreed) {
                    MaterialTheme.colorScheme.error
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
                modifier = Modifier.testTag(
                    if (disagreed) "meal_identity_disagreement_cue" else "meal_identity_prompt",
                ),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(
                    onClick = {
                        onConfirm(record.suggestedIdentity ?: record.displayIdentity.orEmpty())
                    },
                    enabled = !uiState.isSavingIdentity && !record.displayIdentity.isNullOrBlank(),
                    modifier = Modifier.testTag("meal_identity_confirm"),
                ) { Text(if (uiState.isSavingIdentity) "Confirming…" else "Confirm") }
                OutlinedButton(
                    onClick = onStartEdit,
                    enabled = !uiState.isSavingIdentity,
                    modifier = Modifier.testTag("meal_identity_correct"),
                ) { Text("Correct") }
            }
        }
    }
}

@Composable
private fun IdentityEditor(
    initial: String,
    isSaving: Boolean,
    error: String?,
    onConfirm: (String) -> Unit,
    onCancel: () -> Unit,
) {
    var text by remember(initial) { mutableStateOf(initial) }
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("meal_identity_editor"),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                text = "What is this food?",
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurface,
            )
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                label = { Text("Food name") },
                singleLine = true,
                modifier = Modifier
                    .fillMaxWidth()
                    .testTag("meal_identity_input"),
            )
            if (error != null) {
                Text(
                    text = error,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
                OutlinedButton(
                    onClick = onCancel,
                    enabled = !isSaving,
                    modifier = Modifier.weight(1f),
                ) { Text("Cancel") }
                Button(
                    onClick = { onConfirm(text) },
                    enabled = !isSaving,
                    modifier = Modifier
                        .weight(1f)
                        .testTag("meal_identity_save"),
                ) { Text(if (isSaving) "Saving…" else "Confirm") }
            }
        }
    }
}

/**
 * "How was this estimated" provenance (Story 50.H3). Loaded on demand: the raw
 * per-sample reads, how many reads there were, and which source (if any) grounded
 * it. Descriptive only -- no dose, and no self-reported confidence.
 */
@Composable
private fun MealAuditSection(
    uiState: MealLogUiState,
    onLoad: () -> Unit,
    onHide: () -> Unit,
) {
    val audit = uiState.audit
    if (audit == null) {
        TextButton(
            onClick = onLoad,
            enabled = !uiState.isLoadingAudit,
            modifier = Modifier
                .fillMaxWidth()
                .testTag("meal_audit_button"),
        ) { Text(if (uiState.isLoadingAudit) "Loading…" else "How was this estimated?") }
        uiState.auditError?.let {
            Text(
                text = it,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.testTag("meal_audit_error"),
            )
        }
        return
    }
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("meal_audit_detail"),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text(
                text = "How this estimate was reached",
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = audit.samplesUsed?.let {
                    "Read the photo $it time(s); the range reflects how much those " +
                        "reads disagreed."
                } ?: "Estimated from multiple reads of the photo.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            audit.samples.forEach { sample ->
                val carbs = sample.carbs?.let {
                    "${formatEditableGrams(it.lowGrams)}–${formatEditableGrams(it.highGrams)} g"
                } ?: "—"
                Text(
                    text = "• ${sample.identity ?: "unnamed"}: $carbs",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                text = if (audit.grounded) {
                    "Grounded against ${audit.groundingSource ?: "a source"}" +
                        (audit.identityUsed?.let { " (as \"$it\")" } ?: "") + "."
                } else {
                    "Vision-only -- not grounded against an external source."
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.testTag("meal_audit_precedence"),
            )
            TextButton(
                onClick = onHide,
                modifier = Modifier.testTag("meal_audit_hide"),
            ) { Text("Hide") }
        }
    }
}

@Composable
private fun SaveAsCommonFoodDialog(
    isSaving: Boolean,
    onConfirm: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var name by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Save as common food") },
        text = {
            OutlinedTextField(
                value = name,
                onValueChange = { name = it },
                label = { Text("Name") },
                singleLine = true,
                modifier = Modifier
                    .fillMaxWidth()
                    .testTag("meal_save_common_name_input"),
            )
        },
        confirmButton = {
            Button(
                onClick = { onConfirm(name) },
                enabled = name.isNotBlank() && !isSaving,
                modifier = Modifier.testTag("meal_save_common_confirm"),
            ) { Text(if (isSaving) "Saving…" else "Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun UnavailableContent(reason: MealUnavailableReason, onBack: () -> Unit) {
    val (tag, title, body) = when (reason) {
        MealUnavailableReason.VISION -> Triple(
            "meal_vision_unavailable",
            "Vision isn't available on your AI provider",
            "Carb estimates from photos need a vision-capable AI provider. " +
                "Switch to one in the web app Settings, then try again.",
        )
        MealUnavailableReason.NO_PROVIDER -> Triple(
            "meal_no_provider",
            "No AI provider configured",
            "Set up an AI provider in the web app Settings to estimate carbs from a photo.",
        )
    }
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .testTag(tag),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.errorContainer,
        ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Icon(
                imageVector = Icons.Default.Warning,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onErrorContainer,
                modifier = Modifier.size(40.dp),
            )
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onErrorContainer,
                textAlign = TextAlign.Center,
            )
            Text(
                text = body,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onErrorContainer,
                textAlign = TextAlign.Center,
            )
            TextButton(onClick = onBack) { Text("Back") }
        }
    }
}

@Composable
private fun MealUnavailableMessage(title: String, body: String, tag: String) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .testTag(tag),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            modifier = Modifier.padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Icon(
                imageVector = Icons.Default.LocalCafe,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(48.dp),
            )
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
                textAlign = TextAlign.Center,
            )
            Text(
                text = body,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )
        }
    }
}

@Composable
private fun OfflineRetry(onRetry: () -> Unit) {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(
            modifier = Modifier.padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Icon(
                imageVector = Icons.Default.Warning,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.error,
                modifier = Modifier.size(48.dp),
            )
            Text(
                text = "Couldn't reach the server",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Button(onClick = onRetry) { Text("Retry") }
        }
    }
}

@Composable
private fun ErrorBanner(message: String, onDismiss: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("meal_error"),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.error.copy(alpha = 0.15f),
        ),
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = message,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.weight(1f),
            )
            TextButton(onClick = onDismiss) { Text("Dismiss", color = MaterialTheme.colorScheme.error) }
        }
    }
}

/**
 * The just-captured/picked photo, shown above the result. Decoded off the main thread to a small
 * thumbnail; renders nothing (rather than a broken box) if the image can't be read.
 */
@Composable
private fun MealPhotoThumbnail(uri: Uri) {
    val resolver = LocalContext.current.contentResolver
    var thumbnail by remember(uri) { mutableStateOf<ImageBitmap?>(null) }
    LaunchedEffect(uri) {
        thumbnail = withContext(Dispatchers.IO) { decodePhotoThumbnail(resolver, uri) }
    }
    thumbnail?.let { bitmap ->
        Image(
            bitmap = bitmap,
            contentDescription = "Photo of your meal",
            contentScale = ContentScale.Crop,
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(16f / 9f)
                .clip(RoundedCornerShape(12.dp))
                .testTag("meal_result_photo"),
        )
    }
}

/** Decode [uri] to a downscaled [ImageBitmap] for preview, or null if it can't be read. */
private fun decodePhotoThumbnail(resolver: ContentResolver, uri: Uri): ImageBitmap? = runCatching {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) } ?: return null
    if (bounds.outWidth <= 0) return null
    val options = BitmapFactory.Options().apply {
        inSampleSize = Integer.highestOneBit(max(1, bounds.outWidth / THUMBNAIL_TARGET_PX))
    }
    resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, options) }?.asImageBitmap()
}.getOrNull()

// Preview only (renders in a 16:9 strip), so a modest decode target keeps memory low.
private const val THUMBNAIL_TARGET_PX = 720
