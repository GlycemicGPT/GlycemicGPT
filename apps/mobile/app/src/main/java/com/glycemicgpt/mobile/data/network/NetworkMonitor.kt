package com.glycemicgpt.mobile.data.network

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import timber.log.Timber
import java.util.concurrent.atomic.AtomicInteger
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Coarse network status the home screen surfaces so a cached reading is never mistaken for a live
 * one. Three states, deliberately kept distinct:
 *
 * - [REACHABLE] — device online and our backend answered recently.
 * - [BACKEND_UNREACHABLE] — device is online but our server/self-hosted box isn't responding.
 * - [OFFLINE] — the device has no network at all (airplane mode / no Wi-Fi).
 *
 * Device-offline takes precedence: when there's no network we can't distinguish a backend outage
 * from the missing radio, so we report [OFFLINE] rather than misattributing it to the backend.
 */
enum class NetworkStatus { REACHABLE, BACKEND_UNREACHABLE, OFFLINE }

/**
 * The app's single source of truth for connectivity. Combines two independent signals:
 *
 * 1. **Device connectivity** from [ConnectivityManager]'s default-network callback (online/offline).
 * 2. **Backend reachability** derived entirely client-side from the traffic the app already makes —
 *    [recordBackendSuccess] / [recordBackendFailure] are called by [ReachabilityInterceptor] on the
 *    existing OkHttp path. Any HTTP response (even 4xx/5xx) proves the server is reachable; only
 *    transport-level failures (connect refused, timeout, unknown host) count against it, and only
 *    after [FAILURE_THRESHOLD] consecutive failures do we flip to unreachable to avoid flapping on a
 *    single transient blip. There is intentionally **no backend health endpoint** — this stays
 *    mobile-only and split-neutral.
 *
 * Registration is deferred to [start] (called once from the Application) so construction is cheap
 * and the reachability logic is unit-testable without the Android framework.
 */
@Singleton
class NetworkMonitor @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    private val _deviceOnline = MutableStateFlow(true)
    /** Whether the device currently has any active network. Optimistic until the first callback. */
    val deviceOnline: StateFlow<Boolean> = _deviceOnline.asStateFlow()

    private val _backendReachable = MutableStateFlow(true)
    /** Whether our backend has responded more recently than [FAILURE_THRESHOLD] consecutive
     *  transport failures. Optimistic until the first failures accumulate. */
    val backendReachable: StateFlow<Boolean> = _backendReachable.asStateFlow()

    private val _lastSuccessfulResponseAtMs = MutableStateFlow<Long?>(null)
    /** Wall-clock ms of the last HTTP response from the backend, or null if none yet this process. */
    val lastSuccessfulResponseAtMs: StateFlow<Long?> = _lastSuccessfulResponseAtMs.asStateFlow()

    private val _status = MutableStateFlow(NetworkStatus.REACHABLE)
    /** The combined, UI-facing status. Derived synchronously from the two signals above. */
    val status: StateFlow<NetworkStatus> = _status.asStateFlow()

    // Mutated from ReachabilityInterceptor, which runs on OkHttp's (multi-threaded) dispatcher, so
    // the read-modify-write must be atomic — concurrent request completions would otherwise lose an
    // increment and miss the flip to unreachable.
    private val consecutiveFailures = AtomicInteger(0)

    private val callback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) = setDeviceOnline(true)
        override fun onLost(network: Network) = setDeviceOnline(false)
    }

    /**
     * Begin observing device connectivity. Idempotent-safe to call once from the Application's
     * onCreate. Never unregistered — this is an app-lifetime singleton.
     */
    fun start() {
        val cm = context.getSystemService(ConnectivityManager::class.java)
        if (cm == null) {
            Timber.w("ConnectivityManager unavailable; device-connectivity signal disabled")
            return
        }
        // Seed the current state before the first callback so a cold start on an offline device
        // reports OFFLINE immediately rather than the optimistic default.
        setDeviceOnline(hasActiveNetwork(cm))
        try {
            cm.registerDefaultNetworkCallback(callback)
        } catch (e: RuntimeException) {
            // registerDefaultNetworkCallback can throw if too many callbacks are registered.
            Timber.w(e, "Failed to register network callback; device-connectivity signal disabled")
        }
    }

    private fun hasActiveNetwork(cm: ConnectivityManager): Boolean {
        val active = cm.activeNetwork ?: return false
        val caps = cm.getNetworkCapabilities(active) ?: return false
        // A LAN-only network (self-hosted backend, no internet) still counts as "online" — we only
        // need a route to reach the configured server, so INTERNET (a default route) is enough and
        // we deliberately do not require NET_CAPABILITY_VALIDATED.
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    /** Record that the backend returned an HTTP response — it is reachable regardless of status code. */
    fun recordBackendSuccess() {
        consecutiveFailures.set(0)
        _lastSuccessfulResponseAtMs.value = System.currentTimeMillis()
        if (!_backendReachable.value) {
            _backendReachable.value = true
            recompute()
        }
    }

    /** Record a transport-level failure (connect/timeout/unknown-host). Flips to unreachable only
     *  once [FAILURE_THRESHOLD] consecutive failures accrue with no intervening success. */
    fun recordBackendFailure() {
        if (consecutiveFailures.incrementAndGet() >= FAILURE_THRESHOLD && _backendReachable.value) {
            _backendReachable.value = false
            recompute()
        }
    }

    /** Update device-connectivity. Internal so the [callback] and unit tests can drive it. */
    internal fun setDeviceOnline(online: Boolean) {
        if (_deviceOnline.value != online) {
            _deviceOnline.value = online
            recompute()
        }
    }

    private fun recompute() {
        _status.value = when {
            !_deviceOnline.value -> NetworkStatus.OFFLINE
            !_backendReachable.value -> NetworkStatus.BACKEND_UNREACHABLE
            else -> NetworkStatus.REACHABLE
        }
    }

    companion object {
        /** Consecutive transport failures before the backend is declared unreachable. */
        const val FAILURE_THRESHOLD = 2
    }
}
