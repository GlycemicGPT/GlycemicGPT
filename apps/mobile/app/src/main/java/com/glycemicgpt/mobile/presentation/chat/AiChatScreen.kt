package com.glycemicgpt.mobile.presentation.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.automirrored.filled.VolumeOff
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.glycemicgpt.mobile.presentation.common.AppMarkdownText

@Composable
fun AiChatScreen(
    viewModel: AiChatViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    val ttsEnabled by viewModel.ttsEnabled.collectAsState()
    val context = LocalContext.current

    LaunchedEffect(Unit) {
        viewModel.initTts(context)
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .imePadding(),
    ) {
        when (uiState.pageState) {
            is ChatPageState.Loading -> LoadingContent()
            is ChatPageState.NoProvider -> NoProviderContent(modifier = Modifier.testTag("ai_chat_no_provider"))
            is ChatPageState.Offline -> OfflineContent(onRetry = viewModel::checkProvider)
            is ChatPageState.Ready -> ReadyChatContent(
                uiState = uiState,
                ttsEnabled = ttsEnabled,
                onInputChanged = viewModel::onInputChanged,
                onSend = viewModel::sendMessage,
                onClearChat = viewModel::clearChat,
                onClearError = viewModel::clearError,
                onSuggestionClicked = viewModel::onSuggestionClicked,
                onToggleTts = viewModel::toggleTts,
            )
        }
    }
}

@Composable
private fun LoadingContent() {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            CircularProgressIndicator(
                modifier = Modifier.size(48.dp),
                color = MaterialTheme.colorScheme.primary,
            )
            Spacer(modifier = Modifier.height(16.dp))
            Text(
                text = "Checking AI provider...",
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun NoProviderContent(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier.fillMaxSize(),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.padding(32.dp),
        ) {
            Icon(
                imageVector = Icons.Default.Warning,
                contentDescription = "Warning",
                modifier = Modifier.size(64.dp),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(modifier = Modifier.height(16.dp))
            Text(
                text = "No AI Provider Configured",
                style = MaterialTheme.typography.headlineSmall,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = "Configure an AI provider in the web app Settings to use AI Chat.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )
        }
    }
}

@Composable
private fun OfflineContent(onRetry: () -> Unit) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .testTag("ai_chat_offline"),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.padding(32.dp),
        ) {
            Icon(
                imageVector = Icons.Default.Warning,
                contentDescription = "Warning",
                modifier = Modifier.size(64.dp),
                tint = MaterialTheme.colorScheme.error,
            )
            Spacer(modifier = Modifier.height(16.dp))
            Text(
                text = "Unable to Connect",
                style = MaterialTheme.typography.headlineSmall,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = "Check your connection and server URL in Settings.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )
            Spacer(modifier = Modifier.height(16.dp))
            TextButton(onClick = onRetry) {
                Icon(
                    imageVector = Icons.Default.Refresh,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(modifier = Modifier.size(4.dp))
                Text("Retry")
            }
        }
    }
}

@Composable
private fun ColumnScope.ReadyChatContent(
    uiState: AiChatUiState,
    ttsEnabled: Boolean,
    onInputChanged: (String) -> Unit,
    onSend: () -> Unit,
    onClearChat: () -> Unit,
    onClearError: () -> Unit,
    onSuggestionClicked: (String) -> Unit,
    onToggleTts: () -> Unit,
) {
    val listState = rememberLazyListState()

    // Auto-scroll to bottom when messages change
    val itemCount = uiState.messages.size +
        (if (uiState.isSending) 1 else 0) +
        (if (uiState.error != null) 1 else 0) +
        (if (uiState.messages.isEmpty() && !uiState.isSending) 1 else 0)
    LaunchedEffect(uiState.messages.size, uiState.isSending) {
        if (itemCount > 0) {
            listState.animateScrollToItem(itemCount - 1)
        }
    }

    // Header
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = "AI Chat",
            style = MaterialTheme.typography.titleLarge,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.weight(1f),
        )
        IconButton(
            onClick = onToggleTts,
            modifier = Modifier.testTag("ai_chat_tts_toggle"),
        ) {
            Icon(
                imageVector = if (ttsEnabled) Icons.AutoMirrored.Filled.VolumeUp else Icons.AutoMirrored.Filled.VolumeOff,
                contentDescription = if (ttsEnabled) "Disable TTS" else "Enable TTS",
                tint = if (ttsEnabled) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
            )
        }
        if (uiState.messages.isNotEmpty()) {
            IconButton(
                onClick = onClearChat,
                modifier = Modifier.testTag("ai_chat_clear"),
            ) {
                Icon(
                    imageVector = Icons.Default.Delete,
                    contentDescription = "Clear chat",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }

    // Messages list
    LazyColumn(
        state = listState,
        modifier = Modifier
            .weight(1f)
            .fillMaxWidth()
            .testTag("ai_chat_messages"),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (uiState.messages.isEmpty() && !uiState.isSending) {
            item {
                EmptyChatContent(onSuggestionClicked = onSuggestionClicked)
            }
        }

        items(uiState.messages, key = { it.id }) { message ->
            MessageBubble(message = message)
        }

        if (uiState.isSending) {
            item {
                TypingIndicator()
            }
        }

        if (uiState.error != null) {
            item {
                ErrorBanner(error = uiState.error, onDismiss = onClearError)
            }
        }
    }

    // Disclaimer
    Text(
        text = "AI responses are informational only. Always consult your healthcare provider.",
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        textAlign = TextAlign.Center,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp),
    )

    // Input row
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        OutlinedTextField(
            value = uiState.inputText,
            onValueChange = onInputChanged,
            modifier = Modifier
                .weight(1f)
                .testTag("ai_chat_input"),
            placeholder = { Text("Ask about your glucose data...") },
            enabled = !uiState.isSending,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
            keyboardActions = KeyboardActions(onSend = { onSend() }),
            singleLine = true,
            shape = RoundedCornerShape(24.dp),
        )
        IconButton(
            onClick = onSend,
            enabled = uiState.inputText.isNotBlank() && !uiState.isSending,
            modifier = Modifier.testTag("ai_chat_send"),
        ) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.Send,
                contentDescription = "Send",
                tint = if (uiState.inputText.isNotBlank() && !uiState.isSending) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
            )
        }
    }
}

@Composable
private fun MessageBubble(message: ChatMessage) {
    val isUser = message.role == MessageRole.USER

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp),
        horizontalAlignment = if (isUser) Alignment.End else Alignment.Start,
    ) {
        Card(
            modifier = Modifier.widthIn(max = 300.dp),
            shape = RoundedCornerShape(
                topStart = 16.dp,
                topEnd = 16.dp,
                bottomStart = if (isUser) 16.dp else 4.dp,
                bottomEnd = if (isUser) 4.dp else 16.dp,
            ),
            colors = CardDefaults.cardColors(
                containerColor = if (isUser) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.surfaceVariant
                },
            ),
        ) {
            if (isUser) {
                Text(
                    text = message.content,
                    modifier = Modifier.padding(12.dp),
                    color = MaterialTheme.colorScheme.onPrimary,
                    style = MaterialTheme.typography.bodyMedium,
                )
            } else {
                AppMarkdownText(
                    markdown = message.content,
                    modifier = Modifier.padding(12.dp),
                )
            }
        }

        if (!isUser && message.disclaimer != null) {
            Text(
                text = message.disclaimer,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(start = 8.dp, top = 2.dp),
            )
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun EmptyChatContent(onSuggestionClicked: (String) -> Unit) {
    val suggestions = listOf(
        "How am I doing today?",
        "Why do I spike after breakfast?",
        "What are my patterns this week?",
        "How is my time in range?",
    )

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(modifier = Modifier.height(48.dp))
        Text(
            text = "Ask me about your glucose data",
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(modifier = Modifier.height(16.dp))
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            suggestions.forEach { suggestion ->
                AssistChip(
                    onClick = { onSuggestionClicked(suggestion) },
                    label = { Text(suggestion) },
                    modifier = Modifier.testTag("ai_chat_suggestion_chip"),
                    colors = AssistChipDefaults.assistChipColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant,
                        labelColor = MaterialTheme.colorScheme.onSurface,
                    ),
                )
            }
        }
    }
}

@Composable
private fun TypingIndicator() {
    Row(
        modifier = Modifier
            .padding(horizontal = 12.dp)
            .testTag("ai_chat_typing"),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CircularProgressIndicator(
            modifier = Modifier.size(16.dp),
            strokeWidth = 2.dp,
            color = MaterialTheme.colorScheme.primary,
        )
        Spacer(modifier = Modifier.size(8.dp))
        Text(
            text = "AI is thinking...",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun ErrorBanner(error: String, onDismiss: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.error.copy(alpha = 0.15f),
        ),
        shape = RoundedCornerShape(8.dp),
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = error,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.weight(1f),
            )
            TextButton(onClick = onDismiss) {
                Text("Dismiss", color = MaterialTheme.colorScheme.error)
            }
        }
    }
}
