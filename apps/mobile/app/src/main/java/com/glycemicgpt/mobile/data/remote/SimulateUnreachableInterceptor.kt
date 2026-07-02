package com.glycemicgpt.mobile.data.remote

import com.glycemicgpt.mobile.BuildConfig
import com.glycemicgpt.mobile.data.local.AppSettingsStore
import okhttp3.Interceptor
import okhttp3.Response
import java.io.IOException
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Debug-only fault injection: when the "simulate backend unreachable" toggle is on, every request
 * through this interceptor fails with an [IOException] before reaching the network, so the
 * unreachable state is reproducible on an emulator without real network chaos.
 *
 * Split from [ReachabilityInterceptor] so the fault covers ALL backend clients — including the
 * long-timeout chat/LLM client, which deliberately drops [ReachabilityInterceptor] (an LLM
 * inference timeout must not count toward the reachability failure threshold) but must still be
 * fault-injectable. On the main client this sits below [ReachabilityInterceptor], so the injected
 * failure propagates up through it and is recorded exactly like a real transport failure.
 *
 * Compiled to a no-op in release ([AppSettingsStore.simulateBackendUnreachable] is always false
 * there).
 */
@Singleton
class SimulateUnreachableInterceptor @Inject constructor(
    private val appSettingsStore: AppSettingsStore,
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        if (BuildConfig.DEBUG && appSettingsStore.simulateBackendUnreachable) {
            throw IOException("Simulated backend unreachable (debug fault injection)")
        }
        return chain.proceed(chain.request())
    }
}
