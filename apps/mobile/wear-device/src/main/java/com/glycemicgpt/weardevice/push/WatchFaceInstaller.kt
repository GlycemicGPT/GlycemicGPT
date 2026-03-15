package com.glycemicgpt.weardevice.push

import android.content.Context
import android.os.Build
import android.os.ParcelFileDescriptor
import androidx.annotation.RequiresApi
import androidx.wear.watchface.push.WatchFacePushManager
import com.google.android.wearable.watchface.validator.client.DwfValidatorFactory
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.io.File

/**
 * Wraps [WatchFacePushManager] to install, update, and activate watch faces
 * received from the phone app via the Watch Face Push API (Wear OS 6+).
 *
 * All public methods check for API 36+ at runtime and return appropriate
 * error results on older devices. The Push API is only available on Wear OS 6.
 */
class WatchFaceInstaller(private val context: Context) {

    sealed class Result {
        data class Installed(val slotId: String) : Result()
        data class Updated(val slotId: String) : Result()
        data class Error(val message: String) : Result()
    }

    companion object {
        private const val WEAR_OS_6_API = 36
        /**
         * Marker substring present in all GlycemicGPT watch face package names.
         * Debug: com.glycemicgpt.mobile.debug.watchfacepush.glycemicgpt
         * Release: com.glycemicgpt.mobile.watchfacepush.glycemicgpt
         */
        private const val WATCHFACE_PACKAGE_MARKER = ".watchfacepush."

        fun isSupported(): Boolean = Build.VERSION.SDK_INT >= WEAR_OS_6_API
    }

    /**
     * Install or update the watch face from the given APK file.
     * If a GlycemicGPT face already exists, updates it; otherwise installs new.
     * After install/update, activates the face.
     *
     * Returns [Result.Error] on devices running below Wear OS 6 (API 36).
     */
    suspend fun installOrUpdate(apkFile: File): Result {
        if (!isSupported()) {
            return Result.Error("Watch Face Push requires Wear OS 6 (API $WEAR_OS_6_API)")
        }
        return installOrUpdateInternal(apkFile)
    }

    /**
     * List currently installed GlycemicGPT watch faces.
     * Returns empty list on unsupported devices.
     */
    suspend fun listFaces(): List<WatchFacePushManager.WatchFaceDetails> {
        if (!isSupported()) return emptyList()
        return listFacesInternal()
    }

    /**
     * Check if a GlycemicGPT watch face is currently active.
     * Returns false on unsupported devices.
     */
    suspend fun isActive(slotId: String): Boolean {
        if (!isSupported()) return false
        return isActiveInternal(slotId)
    }

    /**
     * Remove a watch face by slot ID.
     * Returns false on unsupported devices.
     */
    suspend fun remove(slotId: String): Boolean {
        if (!isSupported()) return false
        return removeInternal(slotId)
    }

    @RequiresApi(WEAR_OS_6_API)
    private suspend fun installOrUpdateInternal(apkFile: File): Result {
        val pushManager = WatchFacePushManager(context)
        return try {
            val existing = findExistingFace(pushManager)

            if (!apkFile.exists() || !apkFile.canRead()) {
                return Result.Error("APK file not accessible: ${apkFile.name}")
            }

            // Generate validation token using the DWF validator.
            // The Watch Face Push API requires a non-empty token from the validator.
            val token = generateValidationToken(apkFile)
                ?: return Result.Error("Watch face APK failed validation")

            val details = if (existing != null) {
                Timber.d("Updating existing watch face in slot: %s", existing.slotId)
                val pfd = ParcelFileDescriptor.open(apkFile, ParcelFileDescriptor.MODE_READ_ONLY)
                try {
                    pushManager.updateWatchFace(existing.slotId, pfd, token)
                } finally {
                    pfd.close()
                }
            } else {
                Timber.d("Installing new watch face")
                try {
                    val pfd = ParcelFileDescriptor.open(apkFile, ParcelFileDescriptor.MODE_READ_ONLY)
                    try {
                        pushManager.addWatchFace(pfd, token)
                    } finally {
                        pfd.close()
                    }
                } catch (e: WatchFacePushManager.AddWatchFaceException) {
                    rethrowIfCancellation(e)
                    // Slot limit reached: remove all our old faces and retry once.
                    // Note: AddWatchFaceException does not expose error codes or subtypes,
                    // so we rely on message text matching. This is fragile but is the only
                    // detection method available in the current Wear OS Push API.
                    if (e.message?.contains("limit", ignoreCase = true) == true) {
                        Timber.w("Slot limit reached, removing old faces and retrying")
                        removeAllOurFaces(pushManager)
                        val pfd = ParcelFileDescriptor.open(apkFile, ParcelFileDescriptor.MODE_READ_ONLY)
                        try {
                            pushManager.addWatchFace(pfd, token)
                        } finally {
                            pfd.close()
                        }
                    } else {
                        throw e
                    }
                }
            }

            val slotId = details.slotId

            // Activate the face
            try {
                pushManager.setWatchFaceAsActive(slotId)
                Timber.d("Watch face activated: slot=%s", slotId)
            } catch (e: WatchFacePushManager.SetWatchFaceAsActiveException) {
                Timber.w(e, "Failed to auto-activate watch face (user may need to set manually)")
            }

            if (existing != null) Result.Updated(slotId) else Result.Installed(slotId)
        } catch (e: WatchFacePushManager.AddWatchFaceException) {
            rethrowIfCancellation(e)
            Result.Error("Install failed: ${e.message}")
        } catch (e: WatchFacePushManager.UpdateWatchFaceException) {
            rethrowIfCancellation(e)
            Result.Error("Update failed: ${e.message}")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            rethrowIfCancellation(e)
            Result.Error("Unexpected error: ${e.message}")
        }
    }

    /**
     * Validate the WFF APK and obtain the validation token required by the Push API.
     * Returns null if validation fails.
     *
     * Runs on [Dispatchers.IO] because the validator performs synchronous file I/O
     * (APK zip extraction, XML parsing, image decoding) that would block the caller.
     */
    private suspend fun generateValidationToken(apkFile: File): String? =
        withContext(Dispatchers.IO) {
            try {
                val validator = DwfValidatorFactory.create()
                // Use the actual package name (including .debug suffix for debug builds).
                // The Watch Face Push API requires the watch face package to start with
                // the client's actual package name, so both the validator and the Push API
                // must see the same (unsanitized) package name.
                val result = validator.validate(apkFile, context.packageName)
                val failures = result.failures()
                if (failures.isEmpty()) {
                    val token = result.validationToken()
                    if (token.isNullOrEmpty()) {
                        Timber.w("Validator returned empty token despite no failures")
                        return@withContext null
                    }
                    Timber.d("Watch face validated, token obtained (%d chars)", token.length)
                    token
                } else {
                    failures.forEach { failure ->
                        Timber.w("Watch face validation failure: %s: %s", failure.name(), failure.failureMessage())
                    }
                    null
                }
            } catch (e: Exception) {
                Timber.e(e, "Failed to run watch face validator")
                null
            }
        }

    @RequiresApi(WEAR_OS_6_API)
    private suspend fun listFacesInternal(): List<WatchFacePushManager.WatchFaceDetails> {
        val pushManager = WatchFacePushManager(context)
        return try {
            pushManager.listWatchFaces().installedWatchFaceDetails
        } catch (e: WatchFacePushManager.ListWatchFacesException) {
            Timber.w(e, "Failed to list watch faces")
            emptyList()
        }
    }

    @RequiresApi(WEAR_OS_6_API)
    private suspend fun isActiveInternal(slotId: String): Boolean {
        val pushManager = WatchFacePushManager(context)
        return try {
            pushManager.isWatchFaceActive(slotId)
        } catch (e: WatchFacePushManager.IsWatchFaceActiveException) {
            Timber.w(e, "Failed to check if watch face is active")
            false
        }
    }

    @RequiresApi(WEAR_OS_6_API)
    private suspend fun removeInternal(slotId: String): Boolean {
        val pushManager = WatchFacePushManager(context)
        return try {
            pushManager.removeWatchFace(slotId)
            true
        } catch (e: WatchFacePushManager.RemoveWatchFaceException) {
            Timber.w(e, "Failed to remove watch face")
            false
        }
    }

    /** Rethrow if the exception's cause chain contains a [CancellationException]. */
    private fun rethrowIfCancellation(e: Throwable) {
        var cause: Throwable? = e.cause
        while (cause != null) {
            if (cause is CancellationException) throw cause
            cause = cause.cause
        }
    }

    /**
     * Remove all GlycemicGPT watch faces to free up slots when the limit is reached.
     */
    @RequiresApi(WEAR_OS_6_API)
    private suspend fun removeAllOurFaces(pushManager: WatchFacePushManager) {
        try {
            val response = pushManager.listWatchFaces()
            response.installedWatchFaceDetails
                .filter { it.packageName.contains(WATCHFACE_PACKAGE_MARKER) }
                .forEach { details ->
                    try {
                        pushManager.removeWatchFace(details.slotId)
                        Timber.d("Removed old watch face: slot=%s package=%s", details.slotId, details.packageName)
                    } catch (e: WatchFacePushManager.RemoveWatchFaceException) {
                        rethrowIfCancellation(e)
                        Timber.w(e, "Failed to remove watch face slot %s", details.slotId)
                    }
                }
        } catch (e: WatchFacePushManager.ListWatchFacesException) {
            rethrowIfCancellation(e)
            Timber.w(e, "Failed to list watch faces for cleanup")
        }
    }

    /**
     * Find an existing GlycemicGPT watch face by matching the [WATCHFACE_PACKAGE_MARKER]
     * substring in the package name. This matches both debug and release variants.
     */
    @RequiresApi(WEAR_OS_6_API)
    private suspend fun findExistingFace(
        pushManager: WatchFacePushManager,
    ): WatchFacePushManager.WatchFaceDetails? {
        return try {
            val response = pushManager.listWatchFaces()
            val faces = response.installedWatchFaceDetails
            faces.forEach { details ->
                Timber.d("Installed watch face: package=%s slot=%s", details.packageName, details.slotId)
            }
            faces.firstOrNull { details ->
                details.packageName.contains(WATCHFACE_PACKAGE_MARKER)
            }
        } catch (e: WatchFacePushManager.ListWatchFacesException) {
            Timber.w(e, "Failed to list watch faces, treating as fresh install")
            null
        }
    }
}
