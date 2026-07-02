package com.glycemicgpt.mobile.data.remote

import com.glycemicgpt.mobile.data.network.NetworkMonitor
import okhttp3.Interceptor
import okhttp3.Response
import java.io.IOException
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Feeds the client-side backend-reachability signal. Sits below the URL/auth/token
 * interceptors in the OkHttp chain so it wraps the actual network call: a config-time throw from
 * [BaseUrlInterceptor] (no server configured) happens above it and is never counted as a backend
 * outage, while a real connect/timeout failure propagates up through it and is.
 *
 * Any [Response] — including 4xx/5xx — means the server answered, so it counts as reachable; only an
 * [IOException] (transport failure) counts against reachability. See [NetworkMonitor] for how the
 * consecutive-failure threshold turns that into the "backend unreachable" state.
 *
 * The debug "simulate backend unreachable" fault lives in [SimulateUnreachableInterceptor], which
 * sits below this one so an injected fault is recorded exactly like a real transport failure.
 */
@Singleton
class ReachabilityInterceptor @Inject constructor(
    private val networkMonitor: NetworkMonitor,
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        return try {
            val response = chain.proceed(chain.request())
            networkMonitor.recordBackendSuccess()
            response
        } catch (e: IOException) {
            // A canceled call (ViewModel scope teardown, navigation, a superseded request) also
            // surfaces as an IOException but is NOT a reachability signal — only genuine transport
            // failures count, so don't let cancellation pollute the consecutive-failure counter.
            if (!chain.call().isCanceled()) {
                networkMonitor.recordBackendFailure()
            }
            throw e
        }
    }
}
