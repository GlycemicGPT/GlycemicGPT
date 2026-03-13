package com.glycemicgpt.weardevice.push

import android.content.Context
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class WatchFaceInstallerTest {

    @Test
    fun `Result sealed class covers all cases`() {
        val installed: WatchFaceInstaller.Result = WatchFaceInstaller.Result.Installed("slot-1")
        val updated: WatchFaceInstaller.Result = WatchFaceInstaller.Result.Updated("slot-2")
        val error: WatchFaceInstaller.Result = WatchFaceInstaller.Result.Error("something failed")

        assertTrue(installed is WatchFaceInstaller.Result.Installed)
        assertTrue(updated is WatchFaceInstaller.Result.Updated)
        assertTrue(error is WatchFaceInstaller.Result.Error)
    }

    @Test
    fun `Installed result contains slot ID`() {
        val result = WatchFaceInstaller.Result.Installed("test-slot-abc")
        assertEquals("test-slot-abc", result.slotId)
    }

    @Test
    fun `Updated result contains slot ID`() {
        val result = WatchFaceInstaller.Result.Updated("test-slot-xyz")
        assertEquals("test-slot-xyz", result.slotId)
    }

    @Test
    fun `Error result contains message`() {
        val result = WatchFaceInstaller.Result.Error("Install failed: bad APK")
        assertEquals("Install failed: bad APK", result.message)
    }

    @Test
    fun `isSupported returns false on API below 36`() {
        // In unit tests, Build.VERSION.SDK_INT is 0 (not a real device)
        assertFalse(WatchFaceInstaller.isSupported())
    }

    @Test
    fun `installOrUpdate returns error on unsupported API`() = runTest {
        // Build.VERSION.SDK_INT is 0 in unit tests -- below API 36 threshold
        val context = mockk<Context>()
        val installer = WatchFaceInstaller(context)
        val result = installer.installOrUpdate(File("/nonexistent.apk"))

        assertTrue(result is WatchFaceInstaller.Result.Error)
        val error = result as WatchFaceInstaller.Result.Error
        assertTrue(error.message.contains("Wear OS 6"))
    }
}
