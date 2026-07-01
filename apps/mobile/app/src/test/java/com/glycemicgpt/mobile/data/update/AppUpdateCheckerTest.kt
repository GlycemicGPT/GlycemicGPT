package com.glycemicgpt.mobile.data.update

import com.squareup.moshi.Moshi
import io.mockk.mockk
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class AppUpdateCheckerTest {

    @Test
    fun `parseVersionCode for simple version`() {
        assertEquals(1_000_000, AppUpdateChecker.parseVersionCode("1.0.0"))
    }

    @Test
    fun `parseVersionCode for patch version`() {
        assertEquals(1_000_003, AppUpdateChecker.parseVersionCode("1.0.3"))
    }

    @Test
    fun `parseVersionCode for minor version`() {
        assertEquals(1_020_000, AppUpdateChecker.parseVersionCode("1.2.0"))
    }

    @Test
    fun `parseVersionCode for complex version`() {
        assertEquals(2_050_079, AppUpdateChecker.parseVersionCode("2.5.79"))
    }

    @Test
    fun `parseVersionCode newer is greater`() {
        val old = AppUpdateChecker.parseVersionCode("0.1.79")
        val newer = AppUpdateChecker.parseVersionCode("0.1.80")
        assertTrue(newer > old)
    }

    @Test
    fun `parseVersionCode major bump is greater than minor`() {
        val minorBump = AppUpdateChecker.parseVersionCode("0.99.99")
        val majorBump = AppUpdateChecker.parseVersionCode("1.0.0")
        assertTrue(majorBump > minorBump)
    }

    @Test
    fun `parseVersionCode handles two-part version`() {
        assertEquals(1_020_000, AppUpdateChecker.parseVersionCode("1.2"))
    }

    @Test
    fun `parseVersionCode handles single-part version`() {
        assertEquals(3_000_000, AppUpdateChecker.parseVersionCode("3"))
    }

    // isAllowedDownloadHost tests

    @Test
    fun `isAllowedDownloadHost allows github dot com`() {
        assertTrue(AppUpdateChecker.isAllowedDownloadHost("https://github.com/releases/download/v1.0/app.apk"))
    }

    @Test
    fun `isAllowedDownloadHost allows objects dot githubusercontent`() {
        assertTrue(AppUpdateChecker.isAllowedDownloadHost("https://objects.githubusercontent.com/some-path/app.apk"))
    }

    @Test
    fun `isAllowedDownloadHost blocks arbitrary host`() {
        assertFalse(AppUpdateChecker.isAllowedDownloadHost("https://evil.com/malware.apk"))
    }

    @Test
    fun `isAllowedDownloadHost blocks subdomain spoofing`() {
        assertFalse(AppUpdateChecker.isAllowedDownloadHost("https://evil-github.com/app.apk"))
    }

    @Test
    fun `isAllowedDownloadHost rejects malformed URL`() {
        assertFalse(AppUpdateChecker.isAllowedDownloadHost("not-a-url"))
    }

    // isHttpsUrl tests (APK downloads must be https:// -- a code-execution path)

    @Test
    fun `isHttpsUrl accepts https`() {
        assertTrue(AppUpdateChecker.isHttpsUrl("https://github.com/releases/download/v1.0/app.apk"))
    }

    @Test
    fun `isHttpsUrl rejects http`() {
        assertFalse(AppUpdateChecker.isHttpsUrl("http://github.com/releases/download/v1.0/app.apk"))
    }

    @Test
    fun `isHttpsUrl rejects malformed URL`() {
        assertFalse(AppUpdateChecker.isHttpsUrl("not-a-url"))
    }

    @Test
    fun `isHttpsUrl rejects an opaque https URI without a host`() {
        // "https:payload" is an opaque URI: scheme is https but there is no host.
        assertFalse(AppUpdateChecker.isHttpsUrl("https:payload"))
        assertFalse(AppUpdateChecker.isHttpsUrl("https:///no-host"))
    }

    @Test
    fun `an https URL to an allowed host passes both download guards`() {
        val url = "https://github.com/GlycemicGPT/GlycemicGPT/releases/download/v1.0/app.apk"
        assertTrue(AppUpdateChecker.isHttpsUrl(url))
        assertTrue(AppUpdateChecker.isAllowedDownloadHost(url))
    }

    @Test
    fun `downloadApk rejects an insecure http URL even to an allowed host`() = runTest {
        val checker = AppUpdateChecker(mockk(relaxed = true), Moshi.Builder().build())
        // http:// fails the scheme guard before any host check or network access.
        val result = checker.downloadApk("http://github.com/x/app.apk", "app.apk", 0L)
        assertTrue(result is DownloadResult.Error)
        assertEquals("Download blocked: insecure URL", (result as DownloadResult.Error).message)
    }

    // sanitizeFileName tests

    @Test
    fun `sanitizeFileName strips query string`() {
        assertEquals("app.apk", AppUpdateChecker.sanitizeFileName("app.apk?token=abc"))
    }

    @Test
    fun `sanitizeFileName strips fragment`() {
        assertEquals("app.apk", AppUpdateChecker.sanitizeFileName("app.apk#section"))
    }

    @Test
    fun `sanitizeFileName replaces special characters`() {
        assertEquals("app__release.apk", AppUpdateChecker.sanitizeFileName("app/ release.apk"))
    }

    @Test
    fun `sanitizeFileName returns fallback for empty input`() {
        assertEquals("update.apk", AppUpdateChecker.sanitizeFileName(""))
    }

    @Test
    fun `sanitizeFileName preserves valid name`() {
        assertEquals("GlycemicGPT-0.1.81-release.apk", AppUpdateChecker.sanitizeFileName("GlycemicGPT-0.1.81-release.apk"))
    }

    // parseDevRunNumber tests

    @Test
    fun `parseDevRunNumber extracts run number from dev APK name`() {
        assertEquals(42, AppUpdateChecker.parseDevRunNumber("GlycemicGPT-0.1.95-dev.42-debug.apk"))
    }

    @Test
    fun `parseDevRunNumber extracts large run number`() {
        assertEquals(1234, AppUpdateChecker.parseDevRunNumber("GlycemicGPT-0.2.0-dev.1234-debug.apk"))
    }

    @Test
    fun `parseDevRunNumber returns 0 for stable APK name`() {
        assertEquals(0, AppUpdateChecker.parseDevRunNumber("GlycemicGPT-0.1.95-release.apk"))
    }

    @Test
    fun `parseDevRunNumber returns 0 for non-matching string`() {
        assertEquals(0, AppUpdateChecker.parseDevRunNumber("base.apk"))
    }

    @Test
    fun `parseDevRunNumber returns 0 for empty string`() {
        assertEquals(0, AppUpdateChecker.parseDevRunNumber(""))
    }

    @Test
    fun `parseDevRunNumber newer run number is greater`() {
        val older = AppUpdateChecker.parseDevRunNumber("GlycemicGPT-0.1.95-dev.10-debug.apk")
        val newer = AppUpdateChecker.parseDevRunNumber("GlycemicGPT-0.1.95-dev.11-debug.apk")
        assertTrue(newer > older)
    }

    @Test
    fun `parseDevRunNumber rejects loose match without hyphens`() {
        assertEquals(0, AppUpdateChecker.parseDevRunNumber("some-devtools.5thing.apk"))
    }
}
