package com.glycemicgpt.mobile.ble.connection

import android.annotation.SuppressLint
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import com.glycemicgpt.mobile.ble.protocol.TandemProtocol
import com.glycemicgpt.mobile.domain.model.DiscoveredPump
import com.glycemicgpt.mobile.domain.pump.PumpScanner
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import timber.log.Timber
import javax.inject.Inject

/**
 * Scans for nearby Tandem pumps via BLE.
 *
 * Filters by the Tandem pump service UUID so only compatible devices appear.
 * Emits [DiscoveredPump] items as they are found.
 */
class BleScanner @Inject constructor(
    @ApplicationContext private val context: Context,
) : PumpScanner {

    private val bluetoothManager: BluetoothManager? =
        context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager

    /**
     * Start scanning and emit discovered pumps.
     * Scanning continues until the flow collector cancels.
     */
    @SuppressLint("MissingPermission")
    override fun scan(): Flow<DiscoveredPump> = callbackFlow {
        val adapter = bluetoothManager?.adapter
        val scanner = adapter?.bluetoothLeScanner

        if (scanner == null) {
            Timber.w("BLE scanner not available (adapter=%s)", adapter)
            close()
            return@callbackFlow
        }

        val seen = mutableSetOf<String>()

        val callback = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, result: ScanResult) {
                val device = result.device
                val address = device.address
                if (address in seen) return
                seen.add(address)

                val pump = DiscoveredPump(
                    name = device.name ?: "Tandem Pump",
                    address = address,
                    rssi = result.rssi,
                )
                Timber.d("Discovered pump: %s (%s) rssi=%d", pump.name, pump.address, pump.rssi)
                trySend(pump)
            }

            override fun onScanFailed(errorCode: Int) {
                Timber.e("BLE scan failed: errorCode=%d", errorCode)
                close(IllegalStateException("BLE scan failed: $errorCode"))
            }
        }

        val filters = listOf(
            ScanFilter.Builder()
                .setServiceUuid(TandemProtocol.PUMP_SERVICE_PARCEL)
                .build(),
        )
        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
            .build()

        Timber.d("Starting BLE scan for Tandem pumps")
        scanner.startScan(filters, settings, callback)

        awaitClose {
            Timber.d("Stopping BLE scan")
            scanner.stopScan(callback)
        }
    }
}
