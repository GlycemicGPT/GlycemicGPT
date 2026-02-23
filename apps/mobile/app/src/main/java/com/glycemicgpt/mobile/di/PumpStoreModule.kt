package com.glycemicgpt.mobile.di

import com.glycemicgpt.mobile.data.local.BleDebugStoreAdapter
import com.glycemicgpt.mobile.data.local.PumpCredentialStore
import com.glycemicgpt.mobile.domain.pump.DebugLogger
import com.glycemicgpt.mobile.domain.pump.PumpCredentialProvider
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

/**
 * Hilt module that binds app-level storage implementations to the
 * pump-driver-api interfaces. This allows the tandem-pump-driver module
 * to depend on abstractions rather than concrete Android storage classes.
 */
@Module
@InstallIn(SingletonComponent::class)
abstract class PumpStoreModule {

    @Binds
    @Singleton
    abstract fun bindCredentialProvider(impl: PumpCredentialStore): PumpCredentialProvider

    @Binds
    @Singleton
    abstract fun bindDebugLogger(impl: BleDebugStoreAdapter): DebugLogger
}
