package com.glycemicgpt.mobile.plugin.nightscout

import com.glycemicgpt.mobile.data.remote.GlycemicGptApi
import com.glycemicgpt.mobile.data.remote.dto.NightscoutConnectionDto
import com.glycemicgpt.mobile.domain.plugin.Plugin
import com.glycemicgpt.mobile.domain.plugin.PluginContext
import com.glycemicgpt.mobile.domain.plugin.PluginFactory
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Factory for the Nightscout-source plugin (Story 43.8), bound into the platform's
 * `Set<PluginFactory>` multibinding by [com.glycemicgpt.mobile.di.NightscoutSourceModule].
 * Dependencies come from `:app` (the api + Room + WorkManager wiring) -- which is why this
 * plugin lives in `:app` rather than a standalone module that can't depend on `:app`.
 */
@Singleton
class NightscoutSourceFactory @Inject constructor(
    private val syncManager: NightscoutSyncManager,
    private val store: NightscoutSyncStore,
    private val api: GlycemicGptApi,
) : PluginFactory {

    override val metadata = NightscoutSourcePlugin.METADATA

    override fun create(context: PluginContext): Plugin =
        NightscoutSourcePlugin(
            syncManager = syncManager,
            store = store,
            connectionsProvider = ::fetchConnections,
        )

    private suspend fun fetchConnections(): List<NightscoutConnectionDto> {
        val response = api.listNightscoutConnections()
        return if (response.isSuccessful) {
            response.body()?.connections ?: emptyList()
        } else {
            emptyList()
        }
    }
}
