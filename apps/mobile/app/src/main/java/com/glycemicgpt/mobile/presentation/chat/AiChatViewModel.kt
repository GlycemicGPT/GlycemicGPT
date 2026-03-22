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

data class TtsVoiceOption(
    val name: String,
    val locale: Locale,
    val isDefault: Boolean,
) {
    val displayName: String
        get() {
            val parts = name.split("-", "#")
            val gender = when {
                parts.any { it.contains("female", ignoreCase = true) } -> "Female"
                parts.any { it.contains("male", ignoreCase = true) } -> "Male"
                else -> null
            }
            val label = "${locale.displayLanguage} (${locale.displayCountry})"
            return if (gender != null) "$label - $gender" else label
        }
}

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
    private val wearDataSender: com.glycemicgpt.mobile.wear.WearDataSender,
) : ViewModel() {

    companion object {
        const val MAX_MESSAGE_LENGTH = 2000
        private const val MAX_MESSAGES = 100
    }

    private val _uiState = MutableStateFlow(AiChatUiState())
    val uiState: StateFlow<AiChatUiState> = _uiState.asStateFlow()

    private val _ttsEnabled = MutableStateFlow(false)
    val ttsEnabled: StateFlow<Boolean> = _ttsEnabled.asStateFlow()

    private val _availableVoices = MutableStateFlow<List<TtsVoiceOption>>(emptyList())
    val availableVoices: StateFlow<List<TtsVoiceOption>> = _availableVoices.asStateFlow()

    private val _selectedVoiceName = MutableStateFlow<String?>(null)
    val selectedVoiceName: StateFlow<String?> = _selectedVoiceName.asStateFlow()

    private var tts: TextToSpeech? = null
    @Volatile private var ttsReady = false

    init {
        checkProvider()
        _ttsEnabled.value = appSettingsStore.aiTtsEnabled
        _selectedVoiceName.value = appSettingsStore.aiTtsVoice
    }

    fun initTts(context: Context) {
        if (tts != null) return
        tts = TextToSpeech(context.applicationContext) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.language = Locale.getDefault()
                ttsReady = true
                loadAvailableVoices()
                applySelectedVoice()
                Timber.d("TTS engine initialized")
            } else {
                Timber.w("TTS init failed with status %d", status)
                ttsReady = false
            }
        }
    }

    private fun loadAvailableVoices() {
        val engine = tts ?: return
        val deviceLocale = Locale.getDefault()
        val voices = engine.voices
            ?.filter { it.locale.language == deviceLocale.language && !it.isNetworkConnectionRequired }
            ?.sortedBy { it.name }
            ?.map { TtsVoiceOption(name = it.name, locale = it.locale, isDefault = it.name == engine.defaultVoice?.name) }
            ?: emptyList()
        _availableVoices.value = voices
    }

    private fun applySelectedVoice() {
        val engine = tts ?: return
        val voiceName = appSettingsStore.aiTtsVoice
        if (voiceName.isNotEmpty()) {
            val voice = engine.voices?.find { it.name == voiceName }
            if (voice != null) {
                engine.voice = voice
                return
            }
        }
        // Fall back to default voice
        engine.language = Locale.getDefault()
    }

    fun selectVoice(voiceName: String) {
        appSettingsStore.aiTtsVoice = voiceName
        _selectedVoiceName.value = voiceName
        applySelectedVoice()
    }

    fun toggleTts() {
        val newValue = !appSettingsStore.aiTtsEnabled
        appSettingsStore.aiTtsEnabled = newValue
        _ttsEnabled.value = newValue
        // Sync TTS setting to watch immediately
        viewModelScope.launch {
            try {
                wearDataSender.sendWatchFaceConfig(
                    showIoB = appSettingsStore.watchFaceShowIoB,
                    showGraph = appSettingsStore.watchFaceShowGraph,
                    showAlert = appSettingsStore.watchFaceShowAlert,
                    showSeconds = appSettingsStore.watchFaceShowSeconds,
                    graphRangeHours = appSettingsStore.watchFaceGraphRangeHours,
                    theme = appSettingsStore.watchFaceTheme,
                    aiTtsEnabled = newValue,
                )
            } catch (e: Exception) {
                Timber.w(e, "Failed to sync TTS setting to watch")
            }
        }
    }

    fun stopSpeaking() {
        tts?.stop()
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
        tts?.stop()
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
 * Pre-compiled patterns to strip Markdown for natural TTS readability.
 */
private object TtsMarkdownPatterns {
    val FENCED_CODE = Regex("""```[\s\S]*?```""")
    val HORIZONTAL_RULE = Regex("""^[-*_]{3,}\s*$""", RegexOption.MULTILINE)
    val HEADING = Regex("""^#{1,6}\s+""", RegexOption.MULTILINE)
    val BOLD_ITALIC_STAR = Regex("""\*{3}(.+?)\*{3}""")
    val BOLD_ITALIC_UNDER = Regex("""_{3}(.+?)_{3}""")
    val BOLD_STAR = Regex("""\*{2}(.+?)\*{2}""")
    val BOLD_UNDER = Regex("""_{2}(.+?)_{2}""")
    val ITALIC_STAR = Regex("""\*(.+?)\*""")
    val ITALIC_UNDER = Regex("""(^|\s)_(.+?)_(?=\s|$)""")
    val TABLE_SEPARATOR = Regex("""^\|[-:| ]+\|\s*$""", RegexOption.MULTILINE)
    val TABLE_ROW = Regex("""^\|(.+)\|\s*$""", RegexOption.MULTILINE)
    val BULLET = Regex("""^[-*+]\s+""", RegexOption.MULTILINE)
    val NUMBERED = Regex("""^\d+\.\s+""", RegexOption.MULTILINE)
    val LINK = Regex("""\[(.+?)]\(.+?\)""")
    val IMAGE = Regex("""!\[[^\]]*]\([^)]*\)""")
    val INLINE_CODE = Regex("""`([^`]+)`""")
    val BLANK_LINES = Regex("""\n{3,}""")
}

private fun stripMarkdownForTts(text: String): String {
    return text
        .replace(TtsMarkdownPatterns.FENCED_CODE, "")
        .replace(TtsMarkdownPatterns.HORIZONTAL_RULE, "")
        .replace(TtsMarkdownPatterns.HEADING, "")
        .replace(TtsMarkdownPatterns.BOLD_ITALIC_STAR, "$1")
        .replace(TtsMarkdownPatterns.BOLD_ITALIC_UNDER, "$1")
        .replace(TtsMarkdownPatterns.BOLD_STAR, "$1")
        .replace(TtsMarkdownPatterns.BOLD_UNDER, "$1")
        .replace(TtsMarkdownPatterns.ITALIC_STAR, "$1")
        .replace(TtsMarkdownPatterns.ITALIC_UNDER, "$1$2")
        .replace(TtsMarkdownPatterns.TABLE_SEPARATOR, "")
        .replace(TtsMarkdownPatterns.TABLE_ROW) { match ->
            match.groupValues[1].split("|").joinToString(", ") { it.trim() }
        }
        .replace(TtsMarkdownPatterns.IMAGE, "")
        .replace(TtsMarkdownPatterns.BULLET, "")
        .replace(TtsMarkdownPatterns.NUMBERED, "")
        .replace(TtsMarkdownPatterns.LINK, "$1")
        .replace(TtsMarkdownPatterns.INLINE_CODE, "$1")
        .replace(TtsMarkdownPatterns.BLANK_LINES, "\n")
        .trim()
}
