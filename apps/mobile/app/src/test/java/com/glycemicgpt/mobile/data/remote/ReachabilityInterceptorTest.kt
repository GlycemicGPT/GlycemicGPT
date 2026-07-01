package com.glycemicgpt.mobile.data.remote

import com.glycemicgpt.mobile.BuildConfig
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.network.NetworkMonitor
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import okhttp3.Interceptor
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException

class ReachabilityInterceptorTest {

    private val networkMonitor = mockk<NetworkMonitor>(relaxed = true)
    private val appSettingsStore = mockk<AppSettingsStore>(relaxed = true)
    private val interceptor = ReachabilityInterceptor(networkMonitor, appSettingsStore)

    private val request = Request.Builder().url("http://localhost/api/health").build()

    private fun chainReturning(response: Response): Interceptor.Chain = mockk {
        every { request() } returns request
        every { proceed(any()) } returns response
    }

    private fun chainThrowing(error: IOException, canceled: Boolean = false): Interceptor.Chain = mockk {
        every { request() } returns request
        every { proceed(any()) } throws error
        every { call() } returns mockk { every { isCanceled() } returns canceled }
    }

    private fun okResponse(code: Int = 200): Response = Response.Builder()
        .request(request)
        .protocol(Protocol.HTTP_1_1)
        .code(code)
        .message("OK")
        .body("".toResponseBody(null))
        .build()

    @Test
    fun `a successful response records backend reachable and passes it through`() {
        every { appSettingsStore.simulateBackendUnreachable } returns false
        val response = okResponse()

        val result = interceptor.intercept(chainReturning(response))

        assertEquals(response, result)
        verify(exactly = 1) { networkMonitor.recordBackendSuccess() }
        verify(exactly = 0) { networkMonitor.recordBackendFailure() }
    }

    @Test
    fun `a server error still counts as reachable - the server answered`() {
        every { appSettingsStore.simulateBackendUnreachable } returns false

        interceptor.intercept(chainReturning(okResponse(code = 503)))

        verify(exactly = 1) { networkMonitor.recordBackendSuccess() }
        verify(exactly = 0) { networkMonitor.recordBackendFailure() }
    }

    @Test
    fun `a transport failure records a backend failure and rethrows`() {
        every { appSettingsStore.simulateBackendUnreachable } returns false
        val boom = IOException("connect timed out")

        val thrown = assertThrows(IOException::class.java) {
            interceptor.intercept(chainThrowing(boom))
        }

        assertEquals(boom, thrown)
        verify(exactly = 1) { networkMonitor.recordBackendFailure() }
        verify(exactly = 0) { networkMonitor.recordBackendSuccess() }
    }

    @Test
    fun `a canceled call is not counted as a backend failure`() {
        every { appSettingsStore.simulateBackendUnreachable } returns false
        val canceled = IOException("Canceled")

        assertThrows(IOException::class.java) {
            interceptor.intercept(chainThrowing(canceled, canceled = true))
        }

        verify(exactly = 0) { networkMonitor.recordBackendFailure() }
        verify(exactly = 0) { networkMonitor.recordBackendSuccess() }
    }

    @Test
    fun `debug fault injection short-circuits before the network and records a failure`() {
        // Guarded by BuildConfig.DEBUG, which is true for the debug unit-test variant.
        assertTrue("expected the debug variant for this test", BuildConfig.DEBUG)
        every { appSettingsStore.simulateBackendUnreachable } returns true
        val chain = mockk<Interceptor.Chain> {
            every { request() } returns request
        }

        assertThrows(IOException::class.java) { interceptor.intercept(chain) }

        verify(exactly = 1) { networkMonitor.recordBackendFailure() }
        // proceed() must never be reached when the fault is injected.
        verify(exactly = 0) { chain.proceed(any()) }
    }
}
