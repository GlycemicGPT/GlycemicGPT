package com.glycemicgpt.mobile.logging

import android.content.Context
import com.glycemicgpt.mobile.BuildConfig
import io.sentry.SentryLevel
import io.sentry.SentryOptions
import io.sentry.android.core.SentryAndroid
import io.sentry.android.timber.SentryTimberIntegration
import io.sentry.protocol.User
import timber.log.Timber

/**
 * Initializes Sentry crash/error reporting.
 *
 * Posture (mirrors the backend, locked down for a medical app): error events only, no performance
 * traces, no profiling, no session/release-health telemetry, no Session Replay, no screenshots /
 * view hierarchy, no user-interaction tracking, and `isSendDefaultPii = false`. The DSN is compiled
 * in **only when a developer explicitly provides it at build time** ([BuildConfig.SENTRY_DSN]); it
 * is empty otherwise (release builds, and the CI-published debug `dev-latest` APK), so distributed
 * artifacts never report. When the DSN is blank this is a no-op -- "Sentry disabled".
 *
 * Defense in depth against PHI/PII leaving the device:
 * - [SentryOptions.setBeforeBreadcrumb] drops high-risk auto-instrumentation breadcrumbs (HTTP,
 *   navigation, UI, network) wholesale, since their `data` maps are unbounded.
 * - [SentryOptions.setBeforeSend] runs every surviving string field (message + params, exception
 *   values, breadcrumb message + `data`, tag values) through [ReleaseTree.scrubSensitiveData]
 *   (glucose / token / email redaction), drops `request`, nulls `serverName`, and pins a
 *   non-routable placeholder IP so Sentry cannot geo-locate the real connection IP (a null user was
 *   empirically insufficient -- the server still inferred city-level geo from the ingest IP).
 * - The Timber integration only forwards WARN+ to limit how much raw log text reaches Sentry ahead
 *   of the scrub. Note the Sentry Timber tree sees the *raw* message (not the [ReleaseTree]-scrubbed
 *   one), so `beforeSend` is the real safety net.
 *
 * The project should also have "Prevent Storing of IP Addresses" enabled in Sentry settings as the
 * canonical server-side guarantee; the SDK-side controls here do not depend on it but reinforce it.
 */
object SentryInitializer {

    /**
     * Non-routable placeholder so Sentry cannot geo-locate the user's real connection IP. A null
     * user was empirically insufficient (the server inferred city-level geo from the ingest IP);
     * an explicit unroutable address suppresses it.
     */
    private const val PLACEHOLDER_IP = "0.0.0.0"

    /** Auto-instrumentation breadcrumb categories that routinely carry URLs, params, or routes. */
    private val DROPPED_BREADCRUMB_PREFIXES =
        listOf("http", "navigation", "ui.", "network", "device.event")

    fun init(context: Context) {
        val dsn = BuildConfig.SENTRY_DSN
        if (dsn.isBlank()) {
            Timber.i("Sentry disabled (no DSN for this build)")
            return
        }

        // Monitoring must never crash the app it monitors.
        try {
            SentryAndroid.init(context) { options ->
                options.dsn = dsn
                options.environment = BuildConfig.SENTRY_ENVIRONMENT
                options.release = "${BuildConfig.APPLICATION_ID}@${BuildConfig.VERSION_NAME}"

                // ---- Telemetry off: error events only. ----
                options.isSendDefaultPii = false
                options.isAttachScreenshot = false
                options.isAttachViewHierarchy = false
                options.isEnableUserInteractionTracing = false
                options.isEnableUserInteractionBreadcrumbs = false
                options.isEnableAutoSessionTracking = false
                options.tracesSampleRate = 0.0
                options.profilesSampleRate = 0.0
                // Session Replay is structurally absent (sentry-android-replay is not a dependency).
                // Sentry structured logging is off by default and intentionally not enabled here.

                // Forward Timber WARN+ as events; nothing below WARN becomes a breadcrumb.
                options.addIntegration(
                    SentryTimberIntegration(SentryLevel.ERROR, SentryLevel.WARNING),
                )

                // Drop high-risk auto-instrumentation breadcrumbs before they are attached; scrub
                // whatever survives.
                options.beforeBreadcrumb =
                    SentryOptions.BeforeBreadcrumbCallback { crumb, _ ->
                        val category = crumb.category.orEmpty()
                        if (DROPPED_BREADCRUMB_PREFIXES.any { category.startsWith(it) }) {
                            null
                        } else {
                            crumb.message = scrub(crumb.message)
                            scrubData(crumb.data)
                            crumb
                        }
                    }

                // Final scrub on every outgoing event.
                options.beforeSend =
                    SentryOptions.BeforeSendCallback { event, _ ->
                        event.user = User().apply { ipAddress = PLACEHOLDER_IP }
                        event.serverName = null
                        event.request = null
                        // Strip coarse-location signals from the device context (the SDK collects
                        // these by default); model / OS / memory stay for debugging.
                        event.contexts.device?.apply {
                            timezone = null
                            locale = null
                        }
                        event.message?.let { msg ->
                            msg.formatted = scrub(msg.formatted)
                            msg.message = scrub(msg.message)
                            msg.params = msg.params?.map { scrub(it).orEmpty() }
                        }
                        event.exceptions?.forEach { it.value = scrub(it.value) }
                        event.breadcrumbs?.forEach { crumb ->
                            crumb.message = scrub(crumb.message)
                            scrubData(crumb.data)
                        }
                        event.tags?.keys?.toList()?.forEach { key ->
                            event.tags?.get(key)?.let { event.setTag(key, scrub(it).orEmpty()) }
                        }
                        event
                    }
            }
            Timber.i("Sentry initialized (environment=%s)", BuildConfig.SENTRY_ENVIRONMENT)
        } catch (t: Throwable) {
            Timber.e(t, "Sentry initialization failed; continuing without crash reporting")
        }
    }

    private fun scrub(value: String?): String? = value?.let(ReleaseTree::scrubSensitiveData)

    /** Redact string values in a breadcrumb `data` map in place (keys iterated over a snapshot). */
    private fun scrubData(data: MutableMap<String, Any>?) {
        if (data.isNullOrEmpty()) return
        for (key in data.keys.toList()) {
            val value = data[key]
            if (value is String) {
                data[key] = ReleaseTree.scrubSensitiveData(value)
            }
        }
    }
}
