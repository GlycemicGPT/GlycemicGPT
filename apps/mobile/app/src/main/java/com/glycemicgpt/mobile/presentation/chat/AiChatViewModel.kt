package com.glycemicgpt.mobile.presentation.chat

import android.content.Context
import android.speech.tts.TextToSpeech
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.repository.ChatRepository
import com.glycemicgpt.mobile.data.repository.NoProviderException
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import timber.log.Timber
import java.io.IOException
import java.net.SocketTimeoutException
import java.util.Locale
import java.util.UUID
import javax.inject.Inject

enum class MessageRole { USER, ASSISTANT }

data class ChatMessage(
    val id: String = UUID.randomUUID().toString(),
    val role: MessageRole,
    val content: String,
    val timestampMs: Long = System.currentTimeMillis(),
    val disclaimer: String? = null,
)

sealed class ChatPageState {
    data object Loading : ChatPageState()
    data object NoProvider : ChatPageState()
    data object Ready : ChatPageState()
    data object Offline : ChatPageState()
}

data class AiChatUiState(
    val pageState: ChatPageState = ChatPageState.Loading,
    val messages: List<ChatMessage> = emptyList(),
    val inputText: String = "",
    val isSending: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class AiChatViewModel @Inject constructor(
    private val chatRepository: ChatRepository,
    private val appSettingsStore: AppSettingsStore,
) : ViewModel() {

    companion object {
        const val MAX_MESSAGE_LENGTH = 2000
        private const val MAX_MESSAGES = 100
    }

    private val _uiState = MutableStateFlow(AiChatUiState())
    val uiState: StateFlow<AiChatUiState> = _uiState.asStateFlow()

    private val _ttsEnabled = MutableStateFlow(false)
    val ttsEnabled: StateFlow<Boolean> = _ttsEnabled.asStateFlow()

    private var tts: TextToSpeech? = null
    private var ttsReady = false

    init {
        checkProvider()
        _ttsEnabled.value = appSettingsStore.aiTtsEnabled
    }

    fun initTts(context: Context) {
        if (tts != null) return
        tts = TextToSpeech(context.applicationContext) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.language = Locale.getDefault()
                ttsReady = true
                Timber.d("TTS engine initialized")
            } else {
                Timber.w("TTS init failed with status %d", status)
                ttsReady = false
            }
        }
    }

    fun toggleTts() {
        val newValue = !appSettingsStore.aiTtsEnabled
        appSettingsStore.aiTtsEnabled = newValue
        _ttsEnabled.value = newValue
    }

    private fun speakText(text: String) {
        if (!ttsReady || tts == null) return
        val stripped = stripMarkdownForTts(text)
        if (stripped.isBlank()) return
        tts?.speak(stripped, TextToSpeech.QUEUE_FLUSH, null, UUID.randomUUID().toString())
    }

    fun checkProvider() {
        viewModelScope.launch {
            _uiState.update { it.copy(pageState = ChatPageState.Loading) }
            chatRepository.checkProviderConfigured()
                .onSuccess {
                    _uiState.update { it.copy(pageState = ChatPageState.Ready) }
                }
                .onFailure { e ->
                    val state = if (e is NoProviderException) {
                        ChatPageState.NoProvider
                    } else {
                        ChatPageState.Offline
                    }
                    _uiState.update { it.copy(pageState = state) }
                }
        }
    }

    fun sendMessage() {
        val text = _uiState.value.inputText.trim()
        if (text.isBlank() || _uiState.value.isSending) return
        if (text.length > MAX_MESSAGE_LENGTH) {
            _uiState.update { it.copy(error = "Message is too long (max $MAX_MESSAGE_LENGTH characters)") }
            return
        }

        val userMessage = ChatMessage(role = MessageRole.USER, content = text)
        _uiState.update {
            it.copy(
                messages = (it.messages + userMessage).takeLast(MAX_MESSAGES),
                inputText = "",
                isSending = true,
                error = null,
            )
        }

        viewModelScope.launch {
            chatRepository.sendMessage(text)
                .onSuccess { response ->
                    val assistantMessage = ChatMessage(
                        role = MessageRole.ASSISTANT,
                        content = response.response,
                        disclaimer = response.disclaimer,
                    )
                    _uiState.update {
                        it.copy(
                            messages = (it.messages + assistantMessage).takeLast(MAX_MESSAGES),
                            isSending = false,
                        )
                    }
                    if (appSettingsStore.aiTtsEnabled) {
                        speakText(response.response)
                    }
                }
                .onFailure { e ->
                    _uiState.update {
                        it.copy(
                            isSending = false,
                            error = userFriendlyError(e),
                        )
                    }
                }
        }
    }

    fun onInputChanged(text: String) {
        _uiState.update { it.copy(inputText = text) }
    }

    fun clearChat() {
        _uiState.update { it.copy(messages = emptyList(), error = null) }
    }

    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }

    fun onSuggestionClicked(text: String) {
        _uiState.update { it.copy(inputText = text) }
    }

    override fun onCleared() {
        super.onCleared()
        tts?.stop()
        tts?.shutdown()
        tts = null
        ttsReady = false
    }

    private fun userFriendlyError(e: Throwable): String {
        return when {
            e is SocketTimeoutException -> "AI response took too long. Please try again"
            e is IOException -> "Check your internet connection and try again"
            e.message?.contains("401") == true -> "Session expired. Please sign in again"
            e.message?.let { Regex("HTTP 5\\d{2}").containsMatchIn(it) } == true ->
                "Server error. Please try again later"
            else -> e.message ?: "Failed to get response"
        }
    }
}

/**
 * Strip common Markdown formatting for TTS readability.
 */
private val MD_BOLD = Regex("""\*\*(.+?)\*\*""")
private val MD_ITALIC = Regex("""\*(.+?)\*""")
private val MD_HEADING = Regex("""^#{1,6}\s+""", RegexOption.MULTILINE)
private val MD_BULLET = Regex("""^[-*]\s+""", RegexOption.MULTILINE)
private val MD_NUMBERED = Regex("""^\d+\.\s+""", RegexOption.MULTILINE)
private val MD_LINK = Regex("""\[(.+?)]\(.+?\)""")
private val MD_INLINE_CODE = Regex("""`(.+?)`""")

private fun stripMarkdownForTts(text: String): String {
    var result = text
    result = MD_BOLD.replace(result, "$1")
    result = MD_ITALIC.replace(result, "$1")
    result = MD_HEADING.replace(result, "")
    result = MD_BULLET.replace(result, "")
    result = MD_NUMBERED.replace(result, "")
    result = MD_LINK.replace(result, "$1")
    result = MD_INLINE_CODE.replace(result, "$1")
    return result.trim()
}
