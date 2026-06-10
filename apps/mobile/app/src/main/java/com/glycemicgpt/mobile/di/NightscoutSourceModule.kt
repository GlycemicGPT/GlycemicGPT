package com.glycemicgpt.mobile.di

import android.content.Context
import com.glycemicgpt.mobile.domain.plugin.PluginFactory
import com.glycemicgpt.mobile.plugin.PluginSettingsStoreImpl
import com.glycemicgpt.mobile.plugin.nightscout.NightscoutSourceFactory
import com.glycemicgpt.mobile.plugin.nightscout.NightscoutSourcePlugin
import com.glycemicgpt.mobile.plugin.nightscout.NightscoutSyncStore
import dagger.Binds
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import dagger.multibindings.IntoSet
import javax.inject.Singleton

/**
 * Hilt wiring for the built-in Nightscout-source plugin (Story 43.8). Binds the factory into the
 * platform's `Set<PluginFactory>` multibinding (compile-time discovery, AC1) and provides the
 * shared [NightscoutSyncStore] backed by the plugin's per-plugin SharedPreferences file. Using the
 * canonical plugin id keys the store to the same file the platform's [PluginSettingsStoreImpl]
 * (and the detail-screen connection picker) write through, so the worker reads the user's selection.
 */
@Module
@InstallIn(SingletonComponent::class)
abstract class NightscoutSourceModule {

    @Binds
    @IntoSet
    abstract fun bindNightscoutFactory(impl: NightscoutSourceFactory): PluginFactory

    companion object {

        @Provides
        @Singleton
        fun provideNightscoutSyncStore(@ApplicationContext context: Context): NightscoutSyncStore =
            NightscoutSyncStore(PluginSettingsStoreImpl(context, NightscoutSourcePlugin.PLUGIN_ID))
    }
}
