package com.glycemicgpt.mobile.plugin

import android.content.Context
import io.mockk.every
import io.mockk.mockk
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.Rule
import org.junit.rules.TemporaryFolder
import java.io.File

class DexPluginLoaderTest {

    @get:Rule
    val tempFolder = TemporaryFolder()

    private val context: Context = mockk(relaxed = true)
    private lateinit var filesDir: File
    private lateinit var codeCacheDir: File

    @Before
    fun setUp() {
        filesDir = tempFolder.newFolder("files")
        codeCacheDir = tempFolder.newFolder("code_cache")
        every { context.filesDir } returns filesDir
        every { context.codeCacheDir } returns codeCacheDir
        every { context.classLoader } returns this::class.java.classLoader!!
    }

    @Test
    fun `discover returns empty when plugins dir does not exist`() {
        val loader = DexPluginLoader(context)
        val result = loader.discover()
        assertTrue(result.isEmpty())
    }

    @Test
    fun `discover returns empty when plugins dir is empty`() {
        File(filesDir, "plugins").mkdirs()
        val loader = DexPluginLoader(context)
        val result = loader.discover()
        assertTrue(result.isEmpty())
    }

    @Test
    fun `discover ignores non-jar files`() {
        val pluginsDir = File(filesDir, "plugins")
        pluginsDir.mkdirs()
        File(pluginsDir, "readme.txt").writeText("not a plugin")
        File(pluginsDir, "config.json").writeText("{}")

        val loader = DexPluginLoader(context)
        val result = loader.discover()
        assertTrue(result.isEmpty())
    }

    @Test
    fun `loadJar returns null for jar without manifest`() {
        val pluginsDir = File(filesDir, "plugins")
        pluginsDir.mkdirs()
        val fakeJar = File(pluginsDir, "fake.jar")
        fakeJar.writeText("not a real jar")

        val loader = DexPluginLoader(context)
        // loadJar will fail because it's not a real JAR with DEX bytecode;
        // it should return null and log the error
        val result = loader.loadJar(fakeJar)
        assertEquals(null, result)
    }

    @Test
    fun `PLUGINS_DIR_NAME is correct`() {
        assertEquals("plugins", DexPluginLoader.PLUGINS_DIR_NAME)
    }
}
