/*
 * Medtronic read-only BLE de-risk spike -- peripheral-mode capability probe.
 *
 * Reference code, adapted from OpenMinimed JavaPumpConnector
 * (https://github.com/OpenMinimed/JavaPumpConnector), which is GPL-3.0 and used with the author's
 * permission. Original author: palmarci (Pal Marci) and OpenMinimed contributors. GlycemicGPT is
 * itself GPL-3.0, so this Kotlin adaptation is redistributed under GPL-3.0.
 *
 * This file is NOT wired into a Gradle module yet -- it is the proven reference for the
 * BluetoothLeAdvertiser + BluetoothGattServer peripheral model that the production
 * MedtronicBleConnectionManager builds on. To run it now, drop it into a debug build
 * of :app behind a developer toggle and call probe() on a physical device (peripheral advertising
 * cannot be emulated -- see android-peripheral-probe/README.md). The handshake itself is proven
 * offline by the JVM harness in this same tools/ directory; this probe only answers "can this
 * device act as the BLE peripheral the inverted Medtronic topology requires?".
 *
 * READ-ONLY mandate: this advertises a service and stands up a GATT server so a central can
 * connect. It never writes any therapeutic value to a pump. The SAKE characteristic is NOTIFY+WRITE
 * purely to carry the authentication handshake; no control/calibration path exists or will.
 */
package com.glycemicgpt.medtronicspike.probe

import android.Manifest
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattServer
import android.bluetooth.BluetoothGattServerCallback
import android.bluetooth.BluetoothGattService
import android.bluetooth.BluetoothManager
import android.bluetooth.le.AdvertiseCallback
import android.bluetooth.le.AdvertiseData
import android.bluetooth.le.AdvertiseSettings
import android.bluetooth.le.BluetoothLeAdvertiser
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.ParcelUuid
import android.util.Log
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Result of probing a device for the BLE-peripheral capability the Medtronic 700-series topology
 * needs (the phone advertises as a "Mobile" device and the pump connects to it as central).
 *
 * Every field is an observed fact, so the spike's support matrix is filled from real device output
 * rather than assumption.
 */
data class PeripheralCapability(
    val deviceModel: String,
    val androidApi: Int,
    val hasBlePermissions: Boolean,
    val bleSupported: Boolean,
    val advertiserPresent: Boolean,
    val multipleAdvertisementSupported: Boolean,
    val gattServerOpened: Boolean,
    val sakeServiceAdded: Boolean,
    val advertisingStarted: Boolean,
    val advertisingError: Int?,
    val notes: String,
) {
    /** True only if the device can both advertise the SAKE service and host the GATT server. */
    val isPeripheralCapable: Boolean
        get() = advertiserPresent && gattServerOpened && sakeServiceAdded && advertisingStarted
}

/**
 * Probes one device for peripheral-mode support. Pass an Activity/Service [Context] with the BLE
 * runtime permissions already granted (BLUETOOTH_ADVERTISE + BLUETOOTH_CONNECT on API 31+,
 * ACCESS_FINE_LOCATION below). Call [probe], read the [PeripheralCapability], then [close].
 */
class PeripheralModeProbe(private val context: Context) {

    private val bluetoothManager: BluetoothManager? =
        context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager

    private var gattServer: BluetoothGattServer? = null
    private var advertiseCallback: AdvertiseCallback? = null

    // The exact advertiser instance startAdvertising() was called on, so close() stops the same
    // one (getBluetoothLeAdvertiser() may return a different instance or null at teardown time).
    private var activeAdvertiser: BluetoothLeAdvertiser? = null

    fun probe(): PeripheralCapability {
        val model = "${Build.MANUFACTURER} ${Build.MODEL}"
        val api = Build.VERSION.SDK_INT
        val hasPerms = hasBlePermissions()
        val adapter = bluetoothManager?.adapter

        val bleSupported = context.packageManager.hasSystemFeature(PackageManager.FEATURE_BLUETOOTH_LE)
        if (adapter == null || !bleSupported) {
            return PeripheralCapability(
                model, api, hasPerms, bleSupported,
                advertiserPresent = false,
                multipleAdvertisementSupported = false,
                gattServerOpened = false,
                sakeServiceAdded = false,
                advertisingStarted = false,
                advertisingError = null,
                notes = "No BluetoothAdapter or BLE unsupported (expected on emulators).",
            )
        }

        // The single most decisive check: emulators and some phones return null here.
        val advertiser = adapter.bluetoothLeAdvertiser
        val advertiserPresent = advertiser != null
        val multiAdv = adapter.isMultipleAdvertisementSupported

        if (!hasPerms) {
            return PeripheralCapability(
                model, api, hasPerms, bleSupported, advertiserPresent, multiAdv,
                gattServerOpened = false,
                sakeServiceAdded = false,
                advertisingStarted = false,
                advertisingError = null,
                notes = "BLE runtime permissions not granted; cannot open GATT server.",
            )
        }

        val (serverOpened, sakeAdded) = tryOpenGattServer()
        val (advStarted, advError) = if (advertiserPresent) tryStartAdvertising(adapter) else (false to null)

        return PeripheralCapability(
            model, api, hasPerms, bleSupported, advertiserPresent, multiAdv,
            gattServerOpened = serverOpened,
            sakeServiceAdded = sakeAdded,
            advertisingStarted = advStarted,
            advertisingError = advError,
            notes = if (!advertiserPresent) {
                "getBluetoothLeAdvertiser() returned null -> device cannot act as BLE peripheral."
            } else {
                "Peripheral path exercised; see boolean fields for the verdict."
            },
        )
    }

    private fun tryOpenGattServer(): Pair<Boolean, Boolean> {
        return try {
            val server = bluetoothManager?.openGattServer(context, gattServerCallback) ?: return false to false
            gattServer = server
            val sakeService = BluetoothGattService(SAKE_SERVICE_UUID, BluetoothGattService.SERVICE_TYPE_PRIMARY)
            val sakeChar = BluetoothGattCharacteristic(
                SAKE_CHARACTERISTIC_UUID,
                BluetoothGattCharacteristic.PROPERTY_NOTIFY or BluetoothGattCharacteristic.PROPERTY_WRITE,
                BluetoothGattCharacteristic.PERMISSION_WRITE,
            )
            sakeService.addCharacteristic(sakeChar)

            // addService() only reports that the add was *initiated*; the real outcome arrives on
            // onServiceAdded(). Latch it so the probe records whether the service actually
            // registered, not just that the request was accepted.
            val latch = CountDownLatch(1)
            serviceAddedLatch.set(latch)
            serviceAddedStatus.set(BluetoothGatt.GATT_FAILURE)
            if (!server.addService(sakeService)) {
                return true to false
            }
            val completed = latch.await(SERVICE_ADD_TIMEOUT_SECONDS, TimeUnit.SECONDS)
            val added = completed && serviceAddedStatus.get() == BluetoothGatt.GATT_SUCCESS
            true to added
        } catch (e: SecurityException) {
            Log.e(TAG, "GATT server open denied", e)
            false to false
        }
    }

    private fun tryStartAdvertising(adapter: BluetoothAdapter): Pair<Boolean, Int?> {
        val advertiser = adapter.bluetoothLeAdvertiser ?: return false to null
        activeAdvertiser = advertiser
        val settings = AdvertiseSettings.Builder()
            .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_BALANCED)
            .setConnectable(true)
            .setTimeout(0)
            .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_MEDIUM)
            .build()
        // Advertise as a Medtronic "Mobile" device: company id 0x01f9, SAKE service 0xFE82.
        // The manufacturer payload + 16-bit service UUID + flags must stay under the 31-byte legacy
        // advertising limit, or the stack reports ADVERTISE_FAILED_DATA_TOO_LARGE.
        val data = AdvertiseData.Builder()
            .addManufacturerData(MEDTRONIC_COMPANY_ID, byteArrayOf(0x00) + MOBILE_NAME.toByteArray() + byteArrayOf(0x00))
            .addServiceUuid(ParcelUuid(SAKE_SERVICE_UUID))
            .setIncludeDeviceName(false)
            .build()

        // The advertise callback fires on a binder thread; hand its result back through atomics so
        // the cross-thread contract is explicit (not reliant on closure-capture write visibility).
        val started = AtomicBoolean(false)
        val errorCode = AtomicInteger(NO_ADVERTISE_ERROR)
        val latch = CountDownLatch(1)
        val cb = object : AdvertiseCallback() {
            override fun onStartSuccess(settingsInEffect: AdvertiseSettings) {
                started.set(true)
                latch.countDown()
            }

            override fun onStartFailure(code: Int) {
                errorCode.set(code)
                latch.countDown()
            }
        }
        advertiseCallback = cb
        return try {
            advertiser.startAdvertising(settings, data, cb)
            val signalled = latch.await(ADVERTISE_TIMEOUT_SECONDS, TimeUnit.SECONDS)
            when {
                started.get() -> true to null
                errorCode.get() != NO_ADVERTISE_ERROR -> false to errorCode.get()
                // Neither callback fired in the window: report a sentinel so a timeout is not
                // mistaken for a clean "didn't advertise, no error".
                !signalled -> false to ADVERTISE_CALLBACK_TIMEOUT
                else -> false to null
            }
        } catch (e: SecurityException) {
            Log.e(TAG, "Advertising denied", e)
            false to null
        }
    }

    /** Stop advertising and close the GATT server. Safe to call more than once. */
    fun close() {
        val cb = advertiseCallback
        val advertiser = activeAdvertiser
        if (cb != null && advertiser != null) {
            try {
                advertiser.stopAdvertising(cb)
            } catch (e: SecurityException) {
                Log.e(TAG, "stopAdvertising denied", e)
            }
        }
        advertiseCallback = null
        activeAdvertiser = null
        try {
            gattServer?.close()
        } catch (e: SecurityException) {
            Log.e(TAG, "GATT server close denied", e)
        }
        gattServer = null
    }

    private fun hasBlePermissions(): Boolean = when {
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ->
            context.checkSelfPermission(Manifest.permission.BLUETOOTH_ADVERTISE) == PackageManager.PERMISSION_GRANTED &&
                context.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED
        // Below API 31 the BLUETOOTH / BLUETOOTH_ADMIN install-time permissions are auto-granted,
        // and ACCESS_FINE_LOCATION is required only for BLE *scanning* -- not for advertising or
        // running a GATT server, which is all this peripheral probe does. Gating on location here
        // would understate capability on a device that can advertise without it.
        else -> true
    }

    // Latches the real outcome of addService(), delivered asynchronously to onServiceAdded().
    private val serviceAddedLatch = java.util.concurrent.atomic.AtomicReference<CountDownLatch?>()
    private val serviceAddedStatus = AtomicInteger(BluetoothGatt.GATT_FAILURE)

    // The probe does not drive a handshake; the callback only records the service-add outcome.
    private val gattServerCallback = object : BluetoothGattServerCallback() {
        override fun onServiceAdded(status: Int, service: BluetoothGattService) {
            serviceAddedStatus.set(status)
            serviceAddedLatch.get()?.countDown()
        }
    }

    companion object {
        private const val TAG = "PeripheralModeProbe"

        /** Seconds to wait for the advertise callback before reporting a timeout. */
        private const val ADVERTISE_TIMEOUT_SECONDS = 3L

        /** Seconds to wait for onServiceAdded() before treating the service add as failed. */
        private const val SERVICE_ADD_TIMEOUT_SECONDS = 3L

        /** Sentinel meaning "onStartFailure never delivered a real error code". */
        private const val NO_ADVERTISE_ERROR = -1

        /** advertisingError value used when neither advertise callback fired within the window. */
        const val ADVERTISE_CALLBACK_TIMEOUT = -2

        /** Medtronic Bluetooth SIG company identifier used in the "Mobile" advertisement. */
        const val MEDTRONIC_COMPANY_ID = 0x01f9

        /**
         * Advertised local name the pump expects (must match the regex `Mobile .{0,7}`).
         * NOTE: a constant suffix is fine for a one-shot capability probe, but the production
         * driver must randomize the suffix per OpenMinimed, since the pump tracks
         * the paired phone by this name for reconnects.
         */
        const val MOBILE_NAME = "Mobile 000001"

        /** SAKE service: 16-bit 0xFE82 expanded onto the Bluetooth SIG base UUID. */
        val SAKE_SERVICE_UUID: UUID = UUID.fromString("0000fe82-0000-1000-8000-00805f9b34fb")

        /**
         * SAKE characteristic. NOTE: this uses Medtronic's vendor-specific 128-bit base
         * (`...-0000-009132591325`), NOT the Bluetooth SIG base -- transcribed verbatim from
         * OpenMinimed JavaPumpConnector's BlePeripheralDevice (NOTIFY + WRITE).
         */
        val SAKE_CHARACTERISTIC_UUID: UUID = UUID.fromString("0000fe82-0000-1000-0000-009132591325")
    }
}
