package com.glycemicgpt.mobile.plugin

import android.content.Context
import android.net.Uri
import timber.log.Timber
import java.io.File
import java.io.IOException

/**
 * Manages plugin JAR files on disk: install from content URI, remove, and list.
 *
 * Plugin JARs are stored in `context.filesDir/plugins/`. Only files with a
 * `.jar` extension are accepted.
 */
class PluginFileManager(private val context: Context) {

    private val pluginsDir: File
        get() = File(context.filesDir, DexPluginLoader.PLUGINS_DIR_NAME)

    companion object {
        /** Maximum plugin JAR size: 50 MB. */
        private const val MAX_PLUGIN_SIZE_BYTES = 50L * 1024 * 1024
        /** ZIP/JAR magic bytes: PK\x03\x04 */
        private val ZIP_MAGIC = byteArrayOf(0x50, 0x4B, 0x03, 0x04)
    }

    /** Check that the file starts with ZIP/JAR magic bytes. */
    private fun isValidZip(file: File): Boolean {
        if (file.length() < 4) return false
        val header = ByteArray(4)
        java.io.DataInputStream(file.inputStream()).use { it.readFully(header) }
        return header.contentEquals(ZIP_MAGIC)
    }

    /**
     * Copy a plugin JAR from a content URI to the plugins directory.
     *
     * @return the destination [File] on success, or a failure with the error
     */
    fun installPlugin(sourceUri: Uri): Result<File> {
        return try {
            val dir = pluginsDir
            if (!dir.exists()) {
                dir.mkdirs()
            }

            // Derive filename from the URI's last path segment
            val rawName = sourceUri.lastPathSegment
                ?.substringAfterLast('/')
                ?.takeIf { it.isNotBlank() }
                ?: "plugin_${System.currentTimeMillis()}.jar"

            // Ensure .jar extension
            val fileName = if (rawName.endsWith(".jar", ignoreCase = true)) {
                rawName
            } else {
                return Result.failure(
                    IllegalArgumentException("Only .jar files are accepted, got: $rawName"),
                )
            }

            // Sanitize filename: only allow alphanumeric, dots, hyphens, underscores
            val sanitized = fileName.replace(Regex("[^a-zA-Z0-9._-]"), "_")
            val destFile = File(dir, sanitized)

            // Canonical-path check: prevent path traversal via crafted filenames
            val dirCanonical = dir.canonicalFile
            val destCanonical = destFile.canonicalFile
            if (!destCanonical.path.startsWith(dirCanonical.path + File.separator)) {
                return Result.failure(
                    SecurityException("Plugin filename resolves outside plugins directory"),
                )
            }

            if (destFile.exists()) {
                return Result.failure(
                    IllegalArgumentException("Plugin file already exists: ${destFile.name}"),
                )
            }

            val inputStream = context.contentResolver.openInputStream(sourceUri)
                ?: return Result.failure(IOException("Cannot open URI: $sourceUri"))

            inputStream.use { input ->
                destFile.outputStream().use { output ->
                    var totalBytes = 0L
                    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                    while (true) {
                        val bytesRead = input.read(buffer)
                        if (bytesRead == -1) break
                        totalBytes += bytesRead
                        if (totalBytes > MAX_PLUGIN_SIZE_BYTES) {
                            destFile.delete()
                            return Result.failure(
                                IllegalArgumentException(
                                    "Plugin file exceeds maximum size of ${MAX_PLUGIN_SIZE_BYTES / (1024 * 1024)} MB",
                                ),
                            )
                        }
                        output.write(buffer, 0, bytesRead)
                    }
                }
            }

            // Validate ZIP/JAR magic bytes (PK\x03\x04)
            if (!isValidZip(destFile)) {
                destFile.delete()
                return Result.failure(
                    IllegalArgumentException("File is not a valid JAR/ZIP archive"),
                )
            }

            // Make read-only: Android's DexClassLoader rejects writable DEX files.
            destFile.setReadOnly()

            Timber.d("PluginFileManager: installed %s (%d bytes)", destFile.name, destFile.length())
            Result.success(destFile)
        } catch (e: IOException) {
            Timber.e(e, "PluginFileManager: failed to install plugin from %s", sourceUri)
            Result.failure(e)
        } catch (e: SecurityException) {
            Timber.e(e, "PluginFileManager: security error installing plugin from %s", sourceUri)
            Result.failure(e)
        }
    }

    /**
     * Delete a plugin JAR file.
     *
     * @return true if the file was deleted, false otherwise
     */
    fun removePlugin(jarFile: File): Boolean {
        if (!jarFile.exists()) {
            Timber.w("PluginFileManager: file does not exist: %s", jarFile.absolutePath)
            return false
        }

        // Only allow removing files from the plugins directory.
        // Append File.separator to prevent prefix collisions (e.g. "plugins_evil/").
        val canonical = jarFile.canonicalFile
        val dirCanonical = pluginsDir.canonicalFile
        if (!canonical.path.startsWith(dirCanonical.path + File.separator)) {
            Timber.e("PluginFileManager: refusing to delete file outside plugins dir: %s", canonical.path)
            return false
        }

        // Make writable so we can delete (installPlugin sets read-only for DexClassLoader).
        jarFile.setWritable(true)
        val deleted = jarFile.delete()
        if (deleted) {
            Timber.d("PluginFileManager: removed %s", jarFile.name)
        } else {
            Timber.e("PluginFileManager: failed to delete %s", jarFile.name)
        }
        return deleted
    }

    /**
     * List all JAR files currently in the plugins directory.
     */
    fun listInstalledJars(): List<File> {
        val dir = pluginsDir
        if (!dir.exists() || !dir.isDirectory) {
            return emptyList()
        }
        return dir.listFiles { file -> file.extension == "jar" }?.toList() ?: emptyList()
    }
}
