package com.glycemicgpt.mobile.di

import com.glycemicgpt.mobile.domain.plugin.events.PluginEventBus
import com.glycemicgpt.mobile.domain.pump.HistoryLogParser
import com.glycemicgpt.mobile.domain.pump.PumpConnectionManager
import com.glycemicgpt.mobile.domain.pump.PumpDriver
import com.glycemicgpt.mobile.domain.pump.PumpScanner
import com.glycemicgpt.mobile.plugin.PluginEventBusImpl
import com.glycemicgpt.mobile.plugin.adapter.HistoryLogParserAdapter
import com.glycemicgpt.mobile.plugin.adapter.PumpConnectionAdapter
import com.glycemicgpt.mobile.plugin.adapter.PumpDriverAdapter
import com.glycemicgpt.mobile.plugin.adapter.PumpScannerAdapter
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

/**
 * Provides the plugin event bus and legacy interface adapters.
 *
 * The adapters bridge the deprecated pump interfaces to the [PluginRegistry],
 * so existing consumers (HomeViewModel, PumpPollingOrchestrator, etc.) compile
 * unchanged while the underlying implementation is now plugin-based.
 */
@Suppress("DEPRECATION")
@Module
@InstallIn(SingletonComponent::class)
abstract class PluginModule {

    @Binds
    @Singleton
    abstract fun bindEventBus(impl: PluginEventBusImpl): PluginEventBus

    @Binds
    @Singleton
    abstract fun bindPumpDriver(impl: PumpDriverAdapter): PumpDriver

    @Binds
    @Singleton
    abstract fun bindPumpConnectionManager(impl: PumpConnectionAdapter): PumpConnectionManager

    @Binds
    @Singleton
    abstract fun bindPumpScanner(impl: PumpScannerAdapter): PumpScanner

    @Binds
    @Singleton
    abstract fun bindHistoryLogParser(impl: HistoryLogParserAdapter): HistoryLogParser
}
