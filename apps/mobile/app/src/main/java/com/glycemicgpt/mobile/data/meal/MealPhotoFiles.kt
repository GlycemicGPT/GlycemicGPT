package com.glycemicgpt.mobile.data.meal

import android.content.Context
import android.net.Uri
import androidx.core.content.FileProvider
import java.io.File

/**
 * Manages the transient cache files used to receive a full-resolution capture from the system
 * camera app. The originals are downscaled and re-encoded before upload and deleted afterwards,
 * so no untouched (EXIF-bearing) photo lingers on disk.
 */
object MealPhotoFiles {

    private const val DIR = "meal_photos"

    /** Create a FileProvider URI the camera app can write the captured photo into. */
    fun createCaptureUri(context: Context): Uri {
        val dir = File(context.cacheDir, DIR).apply { mkdirs() }
        val file = File(dir, "capture_${System.currentTimeMillis()}.jpg")
        return FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
    }

    /**
     * Delete the single capture backing [uri] (a no-op for gallery URIs we don't own). Scoped to
     * one file so an in-flight capture is never swept by another capture's cleanup. FileProvider
     * supports delete-by-content-URI; any failure (e.g. a foreign gallery URI) is ignored.
     */
    fun deleteCapture(context: Context, uri: Uri) {
        runCatching { context.contentResolver.delete(uri, null, null) }
    }

    /** Delete any captured originals left in the cache directory (orphan sweep between sessions). */
    fun clearCaptures(context: Context) {
        File(context.cacheDir, DIR).listFiles()?.forEach { it.delete() }
    }
}
