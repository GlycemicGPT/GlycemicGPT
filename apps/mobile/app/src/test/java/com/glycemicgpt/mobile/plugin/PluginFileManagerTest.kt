package com.glycemicgpt.mobile.plugin

import android.content.ContentResolver
import android.content.Context
import android.net.Uri
import io.mockk.every
import io.mockk.mockk
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

class PluginFileManagerTest {

    /** Create minimal valid ZIP/JAR bytes for test purposes. */
    private fun validJarBytes(content: String = "test"): ByteArray {
        val baos = ByteArrayOutputStream()
        ZipOutputStream(baos).use { zos ->
            zos.putNextEntry(ZipEntry("test.txt"))
            zos.write(content.toByteArray())
            zos.closeEntry()
        }
        return baos.toByteArray()
    }

    @get:Rule
    val tempFolder = TemporaryFolder()

    private val context: Context = mockk(relaxed = true)
    private val contentResolver: ContentResolver = mockk(relaxed = true)
    private lateinit var filesDir: File

    @Before
    fun setUp() {
        filesDir = tempFolder.newFolder("files")
        every { context.filesDir } returns filesDir
        every { context.contentResolver } returns contentResolver
    }

    @Test
    fun `installPlugin copies jar to plugins dir`() {
        val jarBytes = validJarBytes("fake jar content")
        val uri: Uri = mockk()
        every { uri.lastPathSegment } returns "my-plugin.jar"
        every { contentResolver.openInputStream(uri) } returns ByteArrayInputStream(jarBytes)

        val manager = PluginFileManager(context)
        val result = manager.installPlugin(uri)

        assertTrue(result.isSuccess)
        val file = result.getOrThrow()
        assertTrue(file.exists())
        assertEquals("my-plugin.jar", file.name)
        assertTrue(file.readBytes().contentEquals(jarBytes))
    }

    @Test
    fun `installPlugin rejects non-jar files`() {
        val uri: Uri = mockk()
        every { uri.lastPathSegment } returns "plugin.zip"

        val manager = PluginFileManager(context)
        val result = manager.installPlugin(uri)

        assertTrue(result.isFailure)
        assertTrue(result.exceptionOrNull()!!.message!!.contains(".jar"))
    }

    @Test
    fun `installPlugin rejects duplicate files`() {
        val pluginsDir = File(filesDir, "plugins")
        pluginsDir.mkdirs()
        File(pluginsDir, "existing.jar").writeText("existing")

        val uri: Uri = mockk()
        every { uri.lastPathSegment } returns "existing.jar"

        val manager = PluginFileManager(context)
        val result = manager.installPlugin(uri)

        assertTrue(result.isFailure)
        assertTrue(result.exceptionOrNull()!!.message!!.contains("already exists"))
    }

    @Test
    fun `removePlugin deletes file`() {
        val pluginsDir = File(filesDir, "plugins")
        pluginsDir.mkdirs()
        val jar = File(pluginsDir, "test.jar")
        jar.writeText("test content")
        assertTrue(jar.exists())

        val manager = PluginFileManager(context)
        val removed = manager.removePlugin(jar)

        assertTrue(removed)
        assertFalse(jar.exists())
    }

    @Test
    fun `removePlugin returns false for nonexistent file`() {
        val manager = PluginFileManager(context)
        val result = manager.removePlugin(File("/nonexistent/path.jar"))
        assertFalse(result)
    }

    @Test
    fun `removePlugin refuses to delete files outside plugins dir`() {
        val outsideFile = tempFolder.newFile("outside.jar")
        outsideFile.writeText("outside")

        val manager = PluginFileManager(context)
        val result = manager.removePlugin(outsideFile)

        assertFalse(result)
        assertTrue(outsideFile.exists())
    }

    @Test
    fun `listInstalledJars returns jar files only`() {
        val pluginsDir = File(filesDir, "plugins")
        pluginsDir.mkdirs()
        File(pluginsDir, "plugin1.jar").writeText("jar1")
        File(pluginsDir, "plugin2.jar").writeText("jar2")
        File(pluginsDir, "readme.txt").writeText("not a jar")

        val manager = PluginFileManager(context)
        val jars = manager.listInstalledJars()

        assertEquals(2, jars.size)
        assertTrue(jars.all { it.extension == "jar" })
    }

    @Test
    fun `listInstalledJars returns empty when dir missing`() {
        val manager = PluginFileManager(context)
        val jars = manager.listInstalledJars()
        assertTrue(jars.isEmpty())
    }

    @Test
    fun `installPlugin creates plugins dir if missing`() {
        val uri: Uri = mockk()
        every { uri.lastPathSegment } returns "new-plugin.jar"
        every { contentResolver.openInputStream(uri) } returns ByteArrayInputStream(validJarBytes())

        assertFalse(File(filesDir, "plugins").exists())

        val manager = PluginFileManager(context)
        val result = manager.installPlugin(uri)

        assertTrue(result.isSuccess)
        assertTrue(File(filesDir, "plugins").exists())
    }

    @Test
    fun `installPlugin rejects non-zip content`() {
        val uri: Uri = mockk()
        every { uri.lastPathSegment } returns "bad-content.jar"
        every { contentResolver.openInputStream(uri) } returns ByteArrayInputStream(
            "this is not a zip file".toByteArray(),
        )

        val manager = PluginFileManager(context)
        val result = manager.installPlugin(uri)

        assertTrue(result.isFailure)
        assertTrue(result.exceptionOrNull()!!.message!!.contains("valid JAR/ZIP"))
        // Verify the invalid file was cleaned up
        assertFalse(File(File(filesDir, "plugins"), "bad-content.jar").exists())
    }

    @Test
    fun `installPlugin sanitizes filename`() {
        val uri: Uri = mockk()
        every { uri.lastPathSegment } returns "my plugin (1).jar"
        every { contentResolver.openInputStream(uri) } returns ByteArrayInputStream(validJarBytes())

        val manager = PluginFileManager(context)
        val result = manager.installPlugin(uri)

        assertTrue(result.isSuccess)
        val file = result.getOrThrow()
        assertNotNull(file)
        // Spaces and parens should be replaced with underscores
        assertFalse(file.name.contains(" "))
        assertFalse(file.name.contains("("))
        assertTrue(file.name.endsWith(".jar"))
    }
}
