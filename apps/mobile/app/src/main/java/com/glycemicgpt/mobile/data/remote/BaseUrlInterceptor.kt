package com.glycemicgpt.mobile.data.remote

import com.glycemicgpt.mobile.BuildConfig
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import com.glycemicgpt.mobile.data.local.AuthTokenStore
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Interceptor
import okhttp3.Response
import java.io.IOException
import javax.inject.Inject
import javax.inject.Singleton

/**
 * OkHttp interceptor that rewrites the request URL to use the dynamic
 * base URL from [AuthTokenStore]. This allows the server address to be
 * configured at runtime (self-hosted deployments).
 *
 * Throws [IOException] if no valid base URL is configured, preventing
 * requests from leaking to the Retrofit placeholder (localhost).
 *
 * Defense-in-depth: re-applies [UrlSecurityPolicy] here so a base URL that ever became
 * inconsistent with the policy (e.g. the insecure-LAN-HTTP opt-in was turned back off after a
 * cleartext URL was saved) can never actually issue a plaintext request to a public host. This is
 * redundant with the save-time [AuthTokenStore] guard, by design.
 */
@Singleton
class BaseUrlInterceptor @Inject constructor(
    private val authTokenStore: AuthTokenStore,
    private val appSettingsStore: AppSettingsStore,
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val original = chain.request()
        val baseUrl = authTokenStore.getBaseUrl()

        if (baseUrl.isNullOrBlank()) {
            throw IOException("Server URL not configured. Go to Settings to set your server address.")
        }

        val parsed = baseUrl.toHttpUrlOrNull()
            ?: throw IOException("Invalid server URL: $baseUrl")

        if (!UrlSecurityPolicy.isAllowed(baseUrl, BuildConfig.DEBUG, appSettingsStore.allowInsecureLanHttp)) {
            // Distinguish "private host but opt-in off" from "public host" so the error is accurate.
            val message = if (UrlSecurityPolicy.isBlockedPendingLanOptIn(baseUrl, BuildConfig.DEBUG)) {
                "Insecure LAN HTTP is off. Enable it in Settings, or use https://."
            } else {
                "Refusing cleartext HTTP to a non-private host. Use https:// or a private/LAN address."
            }
            throw IOException(message)
        }

        val newUrl = original.url.newBuilder()
            .scheme(parsed.scheme)
            .host(parsed.host)
            .port(parsed.port)
            .build()

        val request = original.newBuilder()
            .url(newUrl)
            .build()
        return chain.proceed(request)
    }
}
