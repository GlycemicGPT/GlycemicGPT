package com.glycemicgpt.mobile.data.remote

import com.glycemicgpt.mobile.BuildConfig
import com.glycemicgpt.mobile.data.local.AppSettingsStore
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

class SimulateUnreachableInterceptorTest {

    private val appSettingsStore = mockk<AppSettingsStore>(relaxed = true)
    private val interceptor = SimulateUnreachableInterceptor(appSettingsStore)

    private val request = Request.Builder().url("http://localhost/api/health").build()

    private fun okResponse(): Response = Response.Builder()
        .request(request)
        .protocol(Protocol.HTTP_1_1)
        .code(200)
        .message("OK")
        .body("".toResponseBody(null))
        .build()

    @Test
    fun `fault off passes the request through untouched`() {
        every { appSettingsStore.simulateBackendUnreachable } returns false
        val response = okResponse()
        val chain = mockk<Interceptor.Chain> {
            every { request() } returns request
            every { proceed(any()) } returns response
        }

        assertEquals(response, interceptor.intercept(chain))
    }

    @Test
    fun `debug fault injection short-circuits before the network`() {
        // Guarded by BuildConfig.DEBUG, which is true for the debug unit-test variant.
        assertTrue("expected the debug variant for this test", BuildConfig.DEBUG)
        every { appSettingsStore.simulateBackendUnreachable } returns true
        val chain = mockk<Interceptor.Chain> {
            every { request() } returns request
        }

        assertThrows(IOException::class.java) { interceptor.intercept(chain) }

        // proceed() must never be reached when the fault is injected.
        verify(exactly = 0) { chain.proceed(any()) }
    }
}
