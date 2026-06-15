package com.glycemicgpt.mobile.data.meal

import android.content.ContentResolver
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.media.ExifInterface
import android.net.Uri
import java.io.ByteArrayOutputStream
import java.io.IOException
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * Decodes a picked/captured image and re-encodes it as a downscaled JPEG that fits under the
 * backend's upload cap. Re-encoding via [Bitmap.compress] discards all metadata (EXIF/GPS),
 * which is defense-in-depth on top of the server-side EXIF stripping.
 *
 * The pure sizing helpers are split out so they can be unit-tested without an Android device.
 */
object ImageCompressor {

    /** Longest-edge target for the uploaded image; plenty for vision estimation. */
    const val MAX_DIMENSION = 1280

    /** Hard ceiling on the encoded payload; must stay <= the server's 5 MiB cap. */
    const val MAX_BYTES = 5 * 1024 * 1024

    private const val INITIAL_QUALITY = 90
    private const val MIN_QUALITY = 40
    private const val QUALITY_STEP = 10

    /**
     * Read [uri], downscale, and JPEG-encode under [maxBytes].
     *
     * @throws IOException if the image cannot be opened or decoded.
     */
    fun compress(
        resolver: ContentResolver,
        uri: Uri,
        maxDimension: Int = MAX_DIMENSION,
        maxBytes: Int = MAX_BYTES,
    ): ByteArray {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        // In inJustDecodeBounds mode decodeStream always returns null and only fills `bounds`, so the
        // open must be null-checked on the stream itself; validity is then read off `bounds`.
        (resolver.openInputStream(uri) ?: throw IOException("Could not open image")).use {
            BitmapFactory.decodeStream(it, null, bounds)
        }
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) {
            throw IOException("Could not decode image")
        }

        val decodeOptions = BitmapFactory.Options().apply {
            inSampleSize = calculateInSampleSize(bounds.outWidth, bounds.outHeight, maxDimension)
        }
        val decoded = resolver.openInputStream(uri)?.use {
            BitmapFactory.decodeStream(it, null, decodeOptions)
        } ?: throw IOException("Could not decode image")

        // Bitmap ownership: each step either returns its input unchanged or returns a new bitmap
        // and recycles the one it replaced (`createScaledBitmap`/`applyOrientation` guard `it != src`).
        // So exactly one live bitmap (`oriented`) survives to the encode step, and the `finally`
        // recycles it. No intermediate is leaked and nothing is double-recycled.
        val (targetWidth, targetHeight) =
            targetDimensions(decoded.width, decoded.height, maxDimension)
        val scaled = if (targetWidth != decoded.width || targetHeight != decoded.height) {
            Bitmap.createScaledBitmap(decoded, targetWidth, targetHeight, true)
                .also { if (it != decoded) decoded.recycle() }
        } else {
            decoded
        }
        val oriented = applyOrientation(resolver, uri, scaled)

        return try {
            encodeUnderCap(oriented, maxBytes)
        } finally {
            oriented.recycle()
        }
    }

    /**
     * Power-of-two subsample factor that gets the longest edge at or below [maxDimension] without
     * over-decoding. Matches the BitmapFactory contract (inSampleSize is rounded to a power of two).
     */
    fun calculateInSampleSize(width: Int, height: Int, maxDimension: Int): Int {
        if (maxDimension <= 0) return 1
        var sampleSize = 1
        val longestEdge = max(width, height)
        while (longestEdge / (sampleSize * 2) >= maxDimension) {
            sampleSize *= 2
        }
        return sampleSize
    }

    /** Final dimensions after constraining the longest edge to [maxDimension], preserving aspect. */
    fun targetDimensions(width: Int, height: Int, maxDimension: Int): Pair<Int, Int> {
        if (maxDimension <= 0 || width <= 0 || height <= 0) return width to height
        val longestEdge = max(width, height)
        if (longestEdge <= maxDimension) return width to height
        val scale = maxDimension.toDouble() / longestEdge
        val scaledWidth = max(1, (width * scale).roundToInt())
        val scaledHeight = max(1, (height * scale).roundToInt())
        return scaledWidth to scaledHeight
    }

    private fun encodeUnderCap(bitmap: Bitmap, maxBytes: Int): ByteArray {
        var quality = INITIAL_QUALITY
        var bytes = bitmap.toJpeg(quality)
        while (bytes.size > maxBytes && quality > MIN_QUALITY) {
            quality -= QUALITY_STEP
            bytes = bitmap.toJpeg(quality)
        }
        if (bytes.size > maxBytes) {
            throw IOException("Image is too large to upload after compression")
        }
        return bytes
    }

    /**
     * Re-apply the camera/gallery EXIF orientation (rotation and/or mirroring) before the metadata
     * is dropped by JPEG encoding, so the uploaded pixels are upright.
     */
    private fun applyOrientation(resolver: ContentResolver, uri: Uri, bitmap: Bitmap): Bitmap {
        val orientation = try {
            resolver.openInputStream(uri)?.use { stream ->
                ExifInterface(stream).getAttributeInt(
                    ExifInterface.TAG_ORIENTATION,
                    ExifInterface.ORIENTATION_NORMAL,
                )
            } ?: ExifInterface.ORIENTATION_NORMAL
        } catch (_: Exception) {
            ExifInterface.ORIENTATION_NORMAL
        }

        val matrix = android.graphics.Matrix()
        when (orientation) {
            ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.setScale(-1f, 1f)
            ExifInterface.ORIENTATION_FLIP_VERTICAL -> matrix.setScale(1f, -1f)
            ExifInterface.ORIENTATION_ROTATE_90 -> matrix.setRotate(90f)
            ExifInterface.ORIENTATION_ROTATE_180 -> matrix.setRotate(180f)
            ExifInterface.ORIENTATION_ROTATE_270 -> matrix.setRotate(270f)
            ExifInterface.ORIENTATION_TRANSPOSE -> { matrix.setRotate(90f); matrix.postScale(-1f, 1f) }
            ExifInterface.ORIENTATION_TRANSVERSE -> { matrix.setRotate(270f); matrix.postScale(-1f, 1f) }
            else -> return bitmap
        }
        val transformed = Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
        if (transformed != bitmap) bitmap.recycle()
        return transformed
    }

    private fun Bitmap.toJpeg(quality: Int): ByteArray =
        ByteArrayOutputStream().use { out ->
            compress(Bitmap.CompressFormat.JPEG, quality, out)
            out.toByteArray()
        }
}
