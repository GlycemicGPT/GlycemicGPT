package com.glycemicgpt.mobile.di

import com.glycemicgpt.mobile.ble.connection.BleConnectionManager
import com.glycemicgpt.mobile.ble.connection.BleScanner
import com.glycemicgpt.mobile.ble.connection.TandemBleDriver
import com.glycemicgpt.mobile.ble.messages.TandemHistoryLogParser
import com.glycemicgpt.mobile.domain.pump.HistoryLogParser
import com.glycemicgpt.mobile.domain.pump.PumpConnectionManager
import com.glycemicgpt.mobile.domain.pump.PumpDriver
import com.glycemicgpt.mobile.domain.pump.PumpScanner
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
abstract class PumpModule {

    @Binds
    @Singleton
    abstract fun bindPumpDriver(impl: TandemBleDriver): PumpDriver

    @Binds
    @Singleton
    abstract fun bindPumpConnectionManager(impl: BleConnectionManager): PumpConnectionManager

    @Binds
    @Singleton
    abstract fun bindPumpScanner(impl: BleScanner): PumpScanner

    @Binds
    @Singleton
    abstract fun bindHistoryLogParser(impl: TandemHistoryLogParser): HistoryLogParser
}
