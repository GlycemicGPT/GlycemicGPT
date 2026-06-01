/*
 * GlycemicGPT code (GPL-3.0). Hilt wiring for the Medtronic MiniMed 700-series read-only driver.
 *
 * Mirrors TandemPumpModule: binds the factory into the platform's `Set<PluginFactory>` multibinding so
 * PluginRegistry discovers it. Additionally assembles the B2 peripheral-mode connection manager from
 * the Android peripheral + the dedicated SAKE worker thread, and the C3 read gateway over the
 * post-handshake session.
 */
package com.glycemicgpt.mobile.di

import android.content.Context
import com.glycemicgpt.mobile.ble.connection.AndroidMedtronicPeripheral
import com.glycemicgpt.mobile.ble.connection.HandlerThreadSerialWorker
import com.glycemicgpt.mobile.ble.connection.MedtronicBleConnectionManager
import com.glycemicgpt.mobile.ble.connection.MedtronicPeripheral
import com.glycemicgpt.mobile.ble.connection.SerialWorker
import com.glycemicgpt.mobile.ble.read.MedtronicReadGateway
import com.glycemicgpt.mobile.domain.plugin.PluginFactory
import com.glycemicgpt.mobile.domain.pump.PumpCredentialProvider
import com.glycemicgpt.mobile.plugin.MedtronicPluginFactory
import dagger.Binds
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import dagger.multibindings.IntoSet
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
abstract class MedtronicPumpModule {

    @Binds
    @IntoSet
    abstract fun bindMedtronicFactory(impl: MedtronicPluginFactory): PluginFactory

    companion object {

        @Provides
        @Singleton
        fun providePeripheral(@ApplicationContext context: Context): MedtronicPeripheral =
            AndroidMedtronicPeripheral(context)

        @Provides
        @Singleton
        fun provideSerialWorker(): SerialWorker =
            HandlerThreadSerialWorker(SAKE_WORKER_THREAD_NAME)

        @Provides
        @Singleton
        fun provideConnectionManager(
            peripheral: MedtronicPeripheral,
            worker: SerialWorker,
            credentialStore: PumpCredentialProvider,
        ): MedtronicBleConnectionManager =
            MedtronicBleConnectionManager(
                peripheral = peripheral,
                credentialStore = credentialStore,
                worker = worker,
                scope = CoroutineScope(SupervisorJob() + Dispatchers.IO),
            )

        @Provides
        @Singleton
        fun provideReadGateway(
            connectionManager: MedtronicBleConnectionManager,
        ): MedtronicReadGateway =
            MedtronicReadGateway(
                sessionProvider = { connectionManager.sakeSession },
                // TODO(48.D): supply the on-device BluetoothGatt-client MedtronicGattLink (scoping the
                // shared SIG 0x2A52 RACP characteristic under the CGM vs IDD service). Until the
                // transport lands the gateway reports "not connected"; pairing + handshake already work.
                linkProvider = { null },
            )

        private const val SAKE_WORKER_THREAD_NAME = "medtronic-sake"
    }
}
