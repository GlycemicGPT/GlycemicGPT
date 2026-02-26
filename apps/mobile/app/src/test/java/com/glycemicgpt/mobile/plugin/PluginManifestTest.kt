package com.glycemicgpt.mobile.plugin

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PluginManifestTest {

    @Test
    fun `parse valid manifest`() {
        val json = """
            {
                "factoryClass": "com.example.MyPluginFactory",
                "apiVersion": 1,
                "id": "com.example.my-plugin",
                "name": "My Plugin",
                "version": "1.0.0",
                "author": "Test Author",
                "description": "A test plugin"
            }
        """.trimIndent()

        val manifest = PluginManifest.parse(json)

        assertEquals("com.example.MyPluginFactory", manifest.factoryClass)
        assertEquals(1, manifest.apiVersion)
        assertEquals("com.example.my-plugin", manifest.id)
        assertEquals("My Plugin", manifest.name)
        assertEquals("1.0.0", manifest.version)
        assertEquals("Test Author", manifest.author)
        assertEquals("A test plugin", manifest.description)
    }

    @Test
    fun `parse manifest with optional fields missing`() {
        val json = """
            {
                "factoryClass": "com.example.Factory",
                "apiVersion": 1,
                "id": "com.example.plugin",
                "name": "Plugin",
                "version": "0.1.0"
            }
        """.trimIndent()

        val manifest = PluginManifest.parse(json)

        assertEquals("", manifest.author)
        assertEquals("", manifest.description)
    }

    @Test
    fun `parse fails on missing factoryClass`() {
        val json = """
            {
                "apiVersion": 1,
                "id": "com.example.plugin",
                "name": "Plugin",
                "version": "1.0.0"
            }
        """.trimIndent()

        val thrown = try {
            PluginManifest.parse(json)
            null
        } catch (e: IllegalArgumentException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("factoryClass"))
    }

    @Test
    fun `parse fails on missing id`() {
        val json = """
            {
                "factoryClass": "com.example.Factory",
                "apiVersion": 1,
                "name": "Plugin",
                "version": "1.0.0"
            }
        """.trimIndent()

        val thrown = try {
            PluginManifest.parse(json)
            null
        } catch (e: IllegalArgumentException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("id"))
    }

    @Test
    fun `parse fails on missing apiVersion`() {
        val json = """
            {
                "factoryClass": "com.example.Factory",
                "id": "com.example.plugin",
                "name": "Plugin",
                "version": "1.0.0"
            }
        """.trimIndent()

        val thrown = try {
            PluginManifest.parse(json)
            null
        } catch (e: IllegalArgumentException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("apiVersion"))
    }

    @Test
    fun `parse fails on missing name`() {
        val json = """
            {
                "factoryClass": "com.example.Factory",
                "apiVersion": 1,
                "id": "com.example.plugin",
                "version": "1.0.0"
            }
        """.trimIndent()

        val thrown = try {
            PluginManifest.parse(json)
            null
        } catch (e: IllegalArgumentException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("name"))
    }

    @Test
    fun `parse fails on invalid JSON`() {
        val thrown = try {
            PluginManifest.parse("not json")
            null
        } catch (e: IllegalArgumentException) {
            e
        }
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("Invalid plugin manifest JSON"))
    }

    @Test
    fun `MANIFEST_PATH has correct value`() {
        assertEquals("META-INF/plugin.json", PluginManifest.MANIFEST_PATH)
    }
}
