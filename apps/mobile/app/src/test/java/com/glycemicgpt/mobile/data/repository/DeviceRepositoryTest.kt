package com.glycemicgpt.mobile.data.repository

import android.content.Context
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.content.pm.Signature
import android.content.pm.SigningInfo
import android.os.Build
import android.provider.Settings
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.remote.GlycemicGptApi
import com.glycemicgpt.mobile.data.remote.dto.DeviceRegistrationRequest
import com.glycemicgpt.mobile.data.remote.dto.DeviceRegistrationResponse
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import io.mockk.mockkStatic
import io.mockk.slot
import io.mockk.unmockkAll
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Response

class DeviceRepositoryTest {

    private val context = mockk<Context>(relaxed = true)
    private val api = mockk<GlycemicGptApi>()
    private val appSettingsStore = mockk<AppSettingsStore>(relaxed = true)
    private lateinit var repository: DeviceRepository

    @Before
    fun setup() {
        repository = DeviceRepository(api, appSettingsStore, context)
    }

    @After
    fun tearDown() {
        unmockkAll()
    }

    @Test
    fun `generateFingerprint returns 64 char hex string`() {
        // Mock Settings.Secure.getString
        mockkStatic(Settings.Secure::class)
        every {
            Settings.Secure.getString(any(), Settings.Secure.ANDROID_ID)
        } returns "test_android_id"

        // Mock PackageManager for signing cert
        val pm = mockk<PackageManager>()
        every { context.packageManager } returns pm
        every { context.packageName } returns "com.glycemicgpt.mobile.debug"
        val pkgInfo = mockk<PackageInfo>()
        val signingInfo = mockk<SigningInfo>()
        every { signingInfo.apkContentsSigners } returns arrayOf(Signature("DEADBEEF"))
        pkgInfo.signingInfo = signingInfo
        every { pm.getPackageInfo(any<String>(), any<Int>()) } returns pkgInfo

        val fingerprint = repository.generateFingerprint()

        // SHA-256 produces 64 hex characters
        assertEquals(64, fingerprint.length)
        assertTrue(fingerprint.all { it in "0123456789abcdef" })
    }

    @Test
    fun `registerDevice passes fingerprint and version`() = runTest {
        every { appSettingsStore.deviceToken } returns "existing-token"

        mockkStatic(Settings.Secure::class)
        every {
            Settings.Secure.getString(any(), Settings.Secure.ANDROID_ID)
        } returns "test_android_id"

        val pm = mockk<PackageManager>()
        every { context.packageManager } returns pm
        every { context.packageName } returns "com.glycemicgpt.mobile.debug"
        val pkgInfo = mockk<PackageInfo>()
        val signingInfo = mockk<SigningInfo>()
        every { signingInfo.apkContentsSigners } returns arrayOf(Signature("DEADBEEF"))
        pkgInfo.signingInfo = signingInfo
        every { pm.getPackageInfo(any<String>(), any<Int>()) } returns pkgInfo

        val requestSlot = slot<DeviceRegistrationRequest>()
        coEvery { api.registerDevice(capture(requestSlot)) } returns Response.success(
            DeviceRegistrationResponse(id = "uuid-1", deviceToken = "existing-token"),
        )

        val result = repository.registerDevice()

        assertTrue(result.isSuccess)
        val req = requestSlot.captured
        assertNotNull(req.deviceFingerprint)
        assertEquals(64, req.deviceFingerprint?.length)
        assertNotNull(req.appVersion)
        assertNotNull(req.buildType)
    }
}
