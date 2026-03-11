package com.glycemicgpt.weardevice.push

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

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
}
