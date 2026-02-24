package com.glycemicgpt.mobile.di

import com.glycemicgpt.mobile.domain.plugin.PluginFactory
import com.glycemicgpt.mobile.plugin.TandemPluginFactory
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import dagger.multibindings.IntoSet

@Module
@InstallIn(SingletonComponent::class)
abstract class TandemPumpModule {

    @Binds
    @IntoSet
    abstract fun bindTandemFactory(impl: TandemPluginFactory): PluginFactory
}
