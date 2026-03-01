package com.glycemicgpt.mobile.data.repository

import android.content.Context
import android.os.Build
import android.provider.Settings
import com.glycemicgpt.mobile.BuildConfig
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.remote.GlycemicGptApi
import com.glycemicgpt.mobile.data.remote.dto.DeviceRegistrationRequest
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import java.security.MessageDigest
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class DeviceRepository @Inject constructor(
    private val api: GlycemicGptApi,
    private val appSettingsStore: AppSettingsStore,
    @ApplicationContext private val context: Context,
) {

    suspend fun registerDevice(): Result<String> = runCatching {
        val token = appSettingsStore.deviceToken ?: UUID.randomUUID().toString().also {
            appSettingsStore.deviceToken = it
        }
        val deviceName = "${Build.MANUFACTURER} ${Build.MODEL}".trim()
        val response = api.registerDevice(
            DeviceRegistrationRequest(
                deviceToken = token,
                deviceName = deviceName,
                platform = "android",
                deviceFingerprint = generateFingerprint(),
                appVersion = BuildConfig.VERSION_NAME,
                buildType = BuildConfig.BUILD_TYPE,
            ),
        )
        if (response.isSuccessful) {
            Timber.d("Device registered: %s", token.take(8))
            token
        } else {
            throw RuntimeException("Device registration failed: HTTP ${response.code()}")
        }
    }

    suspend fun unregisterDevice(): Result<Unit> = runCatching {
        val token = appSettingsStore.deviceToken ?: return@runCatching
        api.unregisterDevice(token)
        appSettingsStore.deviceToken = null
        Timber.d("Device unregistered")
    }

    internal fun generateFingerprint(): String {
        val androidId = Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ANDROID_ID,
        ) ?: ""
        val packageName = BuildConfig.APPLICATION_ID
        val certHash = getSigningCertHash()
        val raw = "$androidId:$packageName:$certHash"
        val digest = MessageDigest.getInstance("SHA-256")
        return digest.digest(raw.toByteArray()).joinToString("") { "%02x".format(it) }
    }

    @Suppress("DEPRECATION")
    private fun getSigningCertHash(): String {
        return try {
            val pm = context.packageManager
            val signingInfo = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                pm.getPackageInfo(
                    context.packageName,
                    android.content.pm.PackageManager.GET_SIGNING_CERTIFICATES,
                ).signingInfo?.apkContentsSigners?.firstOrNull()?.toByteArray()
            } else {
                pm.getPackageInfo(
                    context.packageName,
                    android.content.pm.PackageManager.GET_SIGNATURES,
                ).signatures?.firstOrNull()?.toByteArray()
            }
            if (signingInfo != null) {
                val digest = MessageDigest.getInstance("SHA-256")
                digest.digest(signingInfo).joinToString("") { "%02x".format(it) }
            } else {
                "unknown"
            }
        } catch (e: Exception) {
            Timber.w(e, "Failed to get signing cert hash")
            "unknown"
        }
    }
}
