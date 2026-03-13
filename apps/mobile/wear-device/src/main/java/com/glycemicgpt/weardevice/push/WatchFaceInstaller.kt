package com.glycemicgpt.weardevice.push

import android.content.Context
import android.os.Build
import android.os.ParcelFileDescriptor
import androidx.annotation.RequiresApi
import androidx.wear.watchface.push.WatchFacePushManager
import com.google.android.wearable.watchface.validator.client.DwfValidatorFactory
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
        /** Base package name for the GlycemicGPT watch face (without build-type suffix). */
        private const val WATCHFACE_PACKAGE_PREFIX = "com.glycemicgpt.watchface"

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

            val pfd = ParcelFileDescriptor.open(apkFile, ParcelFileDescriptor.MODE_READ_ONLY)
            val details = try {
                if (existing != null) {
                    Timber.d("Updating existing watch face in slot: %s", existing.slotId)
                    pushManager.updateWatchFace(existing.slotId, pfd, token)
                } else {
                    Timber.d("Installing new watch face")
                    pushManager.addWatchFace(pfd, token)
                }
            } finally {
                pfd.close()
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
            Result.Error("Install failed: ${e.message}")
        } catch (e: WatchFacePushManager.UpdateWatchFaceException) {
            Result.Error("Update failed: ${e.message}")
        } catch (e: Exception) {
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
                // Strip build-type suffix so the validator sees the base applicationId.
                // context.packageName includes the suffix (e.g., ".debug") in non-release
                // builds, which can cause token mismatch during install.
                val appPackageName = context.packageName
                    .replace(Regex("\\.(debug|staging|beta)$"), "")
                val result = validator.validate(apkFile, appPackageName)
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

    /**
     * Find an existing GlycemicGPT watch face by matching [packageName] prefix.
     * The list order from [WatchFacePushManager.listWatchFaces] is not guaranteed stable,
     * so we match by package name rather than taking the first entry.
     */
    @RequiresApi(WEAR_OS_6_API)
    private suspend fun findExistingFace(
        pushManager: WatchFacePushManager,
    ): WatchFacePushManager.WatchFaceDetails? {
        return try {
            val response = pushManager.listWatchFaces()
            response.installedWatchFaceDetails.firstOrNull { details ->
                details.packageName.startsWith(WATCHFACE_PACKAGE_PREFIX)
            }
        } catch (e: WatchFacePushManager.ListWatchFacesException) {
            Timber.w(e, "Failed to list watch faces, treating as fresh install")
            null
        }
    }
}
