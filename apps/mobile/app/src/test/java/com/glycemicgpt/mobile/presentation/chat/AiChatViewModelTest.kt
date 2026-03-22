package com.glycemicgpt.mobile.presentation.chat

import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.remote.dto.ChatResponse
import com.glycemicgpt.mobile.data.repository.ChatRepository
import com.glycemicgpt.mobile.data.repository.NoProviderException
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class AiChatViewModelTest {

    private val testDispatcher = UnconfinedTestDispatcher()
    private lateinit var repository: ChatRepository
    private lateinit var appSettingsStore: AppSettingsStore

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
        repository = mockk(relaxed = true)
        appSettingsStore = mockk(relaxed = true)
        io.mockk.every { appSettingsStore.aiTtsEnabled } returns false
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun createViewModel(): AiChatViewModel {
        return AiChatViewModel(repository, appSettingsStore)
    }

    // --- Provider check tests ---

    @Test
    fun `checkProvider sets Ready on success`() = runTest {
        coEvery { repository.checkProviderConfigured() } returns Result.success(Unit)

        val vm = createViewModel()
        advanceUntilIdle()

        assertEquals(ChatPageState.Ready, vm.uiState.value.pageState)
    }

    @Test
    fun `checkProvider sets NoProvider on NoProviderException`() = runTest {
        coEvery { repository.checkProviderConfigured() } returns
            Result.failure(NoProviderException("No AI provider configured"))

        val vm = createViewModel()
        advanceUntilIdle()

        assertEquals(ChatPageState.NoProvider, vm.uiState.value.pageState)
    }

    @Test
    fun `checkProvider sets Offline on network error`() = runTest {
        coEvery { repository.checkProviderConfigured() } returns
            Result.failure(java.io.IOException("No route to host"))

        val vm = createViewModel()
        advanceUntilIdle()

        assertEquals(ChatPageState.Offline, vm.uiState.value.pageState)
    }

    @Test
    fun `checkProvider sets Offline on generic exception`() = runTest {
        coEvery { repository.checkProviderConfigured() } returns
            Result.failure(Exception("HTTP 500: Internal Server Error"))

        val vm = createViewModel()
        advanceUntilIdle()

        assertEquals(ChatPageState.Offline, vm.uiState.value.pageState)
    }

    // --- Send message tests ---

    @Test
    fun `sendMessage adds user and assistant messages on success`() = runTest {
        coEvery { repository.checkProviderConfigured() } returns Result.success(Unit)
        coEvery { repository.sendMessage(any()) } returns Result.success(
            ChatResponse(response = "Your levels look great.", disclaimer = "Not medical advice."),
        )

        val vm = createViewModel()
        advanceUntilIdle()

        vm.onInputChanged("How am I doing?")
        vm.sendMessage()
        advanceUntilIdle()

        val messages = vm.uiState.value.messages
        assertEquals(2, messages.size)
        assertEquals(MessageRole.USER, messages[0].role)
        assertEquals("How am I doing?", messages[0].content)
        assertEquals(MessageRole.ASSISTANT, messages[1].role)
        assertEquals("Your levels look great.", messages[1].content)
        assertEquals("Not medical advice.", messages[1].disclaimer)
        assertFalse(vm.uiState.value.isSending)
    }

    @Test
    fun `sendMessage sets user-friendly error on IOException`() = runTest {
        coEvery { repository.checkProviderConfigured() } returns Result.success(Unit)
        coEvery { repository.sendMessage(any()) } returns
            Result.failure(java.io.IOException("No route to host"))

        val vm = createViewModel()
        advanceUntilIdle()

        vm.onInputChanged("test")
        vm.sendMessage()
        advanceUntilIdle()

        assertEquals(1, vm.uiState.value.messages.size)
        assertEquals("Check your internet connection and try again", vm.uiState.value.error)
        assertFalse(vm.uiState.value.isSending)
    }

    @Test
    fun `sendMessage sets user-friendly error on server error`() = runTest {
        coEvery { repository.checkProviderConfigured() } returns Result.success(Unit)
        coEvery { repository.sendMessage(any()) } returns
            Result.failure(Exception("HTTP 500: Internal Server Error"))

        val vm = createViewModel()
        advanceUntilIdle()

        vm.onInputChanged("test")
        vm.sendMessage()
        advanceUntilIdle()

        assertEquals("Server error. Please try again later", vm.uiState.value.error)
    }

    @Test
    fun `sendMessage ignores blank input`() = runTest {
        coEvery { repository.checkProviderConfigured() } returns Result.success(Unit)

        val vm = createViewModel()
        advanceUntilIdle()

        vm.onInputChanged("   ")
        vm.sendMessage()
        advanceUntilIdle()

        assertTrue(vm.uiState.value.messages.isEmpty())
        coVerify(exactly = 0) { repository.sendMessage(any()) }
    }

    @Test
    fun `sendMessage rejects message exceeding max length`() = runTest {
        coEvery { repository.checkProviderConfigured() } returns Result.success(Unit)

        val vm = createViewModel()
        advanceUntilIdle()

        val longMessage = "a".repeat(AiChatViewModel.MAX_MESSAGE_LENGTH + 1)
        vm.onInputChanged(longMessage)
        vm.sendMessage()
        advanceUntilIdle()

        assertTrue(vm.uiState.value.messages.isEmpty())
        assertTrue(vm.uiState.value.error!!.contains("too long"))
        coVerify(exactly = 0) { repository.sendMessage(any()) }
    }

    @Test
    fun `sendMessage accepts message at max length`() = runTest {
        coEvery { repository.checkProviderConfigured() } returns Result.success(Unit)
        coEvery { repository.sendMessage(any()) } returns Result.success(
            ChatResponse(response = "ok", disclaimer = ""),
        )

        val vm = createViewModel()
        advanceUntilIdle()

        val maxMessage = "a".repeat(AiChatViewModel.MAX_MESSAGE_LENGTH)
        vm.onInputChanged(maxMessage)
        vm.sendMessage()
        advanceUntilIdle()

        assertEquals(2, vm.uiState.value.messages.size)
        assertNull(vm.uiState.value.error)
    }

    @Test
    fun `sendMessage ignores when already sending`() = runTest {
        coEvery { repository.checkProviderConfigured() } returns Result.success(Unit)
        coEvery { repository.sendMessage(any()) } coAnswers {
            kotlinx.coroutines.delay(10_000)
            Result.success(ChatResponse(response = "ok", disclaimer = ""))
        }

        val vm = createViewModel()
        advanceUntilIdle()

        vm.onInputChanged("first")
        vm.sendMessage()
        vm.onInputChanged("second")
        vm.sendMessage()

        assertEquals(1, vm.uiState.value.messages.size)
    }

    @Test
    fun `sendMessage clears input text`() = runTest {
        coEvery { repository.checkProviderConfigured() } returns Result.success(Unit)
        coEvery { repository.sendMessage(any()) } returns Result.success(
            ChatResponse(response = "reply", disclaimer = ""),
        )

        val vm = createViewModel()
        advanceUntilIdle()

        vm.onInputChanged("Hello")
        assertEquals("Hello", vm.uiState.value.inputText)
        vm.sendMessage()
        advanceUntilIdle()

        assertEquals("", vm.uiState.value.inputText)
    }

    // --- Other actions ---

    @Test
    fun `onInputChanged updates inputText`() = runTest {
        coEvery { repository.checkProviderConfigured() } returns Result.success(Unit)

        val vm = createViewModel()
        advanceUntilIdle()

        vm.onInputChanged("test input")
        assertEquals("test input", vm.uiState.value.inputText)
    }

    @Test
    fun `clearChat removes all messages and error`() = runTest {
        coEvery { repository.checkProviderConfigured() } returns Result.success(Unit)
        coEvery { repository.sendMessage(any()) } returns Result.success(
            ChatResponse(response = "reply", disclaimer = ""),
        )

        val vm = createViewModel()
        advanceUntilIdle()

        vm.onInputChanged("msg")
        vm.sendMessage()
        advanceUntilIdle()
        assertEquals(2, vm.uiState.value.messages.size)

        vm.clearChat()
        assertTrue(vm.uiState.value.messages.isEmpty())
        assertNull(vm.uiState.value.error)
    }

    @Test
    fun `clearError resets error state`() = runTest {
        coEvery { repository.checkProviderConfigured() } returns Result.success(Unit)
        coEvery { repository.sendMessage(any()) } returns
            Result.failure(Exception("fail"))

        val vm = createViewModel()
        advanceUntilIdle()

        vm.onInputChanged("test")
        vm.sendMessage()
        advanceUntilIdle()
        assertEquals("fail", vm.uiState.value.error)

        vm.clearError()
        assertNull(vm.uiState.value.error)
    }

    @Test
    fun `onSuggestionClicked sets inputText`() = runTest {
        coEvery { repository.checkProviderConfigured() } returns Result.success(Unit)

        val vm = createViewModel()
        advanceUntilIdle()

        vm.onSuggestionClicked("How am I doing today?")
        assertEquals("How am I doing today?", vm.uiState.value.inputText)
    }
}
