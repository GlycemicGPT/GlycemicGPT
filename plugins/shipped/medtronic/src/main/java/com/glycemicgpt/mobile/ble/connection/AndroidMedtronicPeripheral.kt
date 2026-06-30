/*
 * Android BluetoothLeAdvertiser + BluetoothGattServer implementation of [MedtronicPeripheral].
 *
 * GlycemicGPT code (GPL-3.0). Structurally modelled on OpenMinimed's JavaPumpConnector
 * BlePeripheralDevice (GPL-3.0, used with permission): advertise as a "Mobile …" device, stand up a
 * read-only GATT server (SAKE + Device Information), and forward GATT-server events to a
 * [PeripheralListener]. All UUIDs and the advertising contract come from B1's [MedtronicProtocol].
 *
 * This is thin Android glue with no unit-test surface (the Android BLE stack is not mockable in
 * local unit tests); it is exercised over-the-air against a real pump in 48.A2 / Milestone F. The
 * testable connection logic lives in [MedtronicBleConnectionManager] / [SakeHandshakeDriver].
 */
package com.glycemicgpt.mobile.ble.connection

import android.annotation.SuppressLint
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothGattServer
import android.bluetooth.BluetoothGattServerCallback
import android.bluetooth.BluetoothGattService
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.BluetoothStatusCodes
import android.bluetooth.le.AdvertiseCallback
import android.bluetooth.le.AdvertiseData
import android.bluetooth.le.AdvertiseSettings
import android.bluetooth.le.BluetoothLeAdvertiser
import android.content.Context
import android.os.Build
import android.os.ParcelUuid
import com.glycemicgpt.mobile.ble.protocol.MedtronicProtocol
import com.glycemicgpt.mobile.ble.protocol.PduFramer
import timber.log.Timber
import java.util.concurrent.ConcurrentLinkedQueue

/**
 * Real-device [MedtronicPeripheral]. Construct with the application [Context]; permissions
 * (`BLUETOOTH_ADVERTISE` / `BLUETOOTH_CONNECT` on API 31+, `ACCESS_FINE_LOCATION` below) are
 * declared in the module manifest and granted by the host app before use.
 */
@SuppressLint("MissingPermission")
class AndroidMedtronicPeripheral(context: Context) : MedtronicPeripheral {

    private val appContext = context.applicationContext
    private val bluetoothManager: BluetoothManager? =
        appContext.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
    private val adapter get() = bluetoothManager?.adapter

    private var advertiser: BluetoothLeAdvertiser? = null
    private var advertiseCallback: AdvertiseCallback? = null

    // Written when the server is opened (caller/worker thread) and read from sendSakeNotification on
    // the worker thread + the GATT-server callbacks on the binder thread, so they need a memory
    // barrier for the cross-thread reads.
    @Volatile
    private var gattServer: BluetoothGattServer? = null

    @Volatile
    private var sakeCharacteristic: BluetoothGattCharacteristic? = null

    @Volatile
    private var listener: PeripheralListener? = null

    @Volatile
    private var peer: BluetoothDevice? = null

    @Volatile
    private var currentMode: AdvertisingMode = AdvertisingMode.FIRST_PAIR

    @Volatile
    private var currentName: String = MedtronicBleConnectionManager.DEFAULT_LOCAL_NAME

    // Advertising parameters held until the GATT services finish registering (see start()). Set on
    // the worker thread and consumed from onServiceAdded on the binder thread.
    @Volatile
    private var pendingAdvertise: Pair<AdvertisingMode, String>? = null

    // Services are added one at a time: addService -> onServiceAdded -> addNextService (the Android
    // GATT server only accepts a new service once the previous add has completed). The queue is
    // populated on the worker thread but drained from onServiceAdded on the binder thread, so it must
    // be thread-safe.
    private val pendingServices = ConcurrentLinkedQueue<BluetoothGattService>()

    override fun isSupported(): Boolean {
        val ad = adapter ?: return false
        return ad.isEnabled && ad.isMultipleAdvertisementSupported && ad.bluetoothLeAdvertiser != null
    }

    override fun start(mode: AdvertisingMode, localName: String, listener: PeripheralListener) {
        this.listener = listener
        currentMode = mode
        currentName = localName
        if (gattServer == null) {
            // Defer advertising until the SAKE + Device Info services are registered (service adds are
            // async via onServiceAdded): otherwise a fast pump could connect and discover an empty
            // GATT table before the services land.
            pendingAdvertise = mode to localName
            openGattServer()
        } else {
            startAdvertising(mode, localName)
        }
    }

    override fun advertise(mode: AdvertisingMode, localName: String) {
        currentMode = mode
        currentName = localName
        stopAdvertising()
        startAdvertising(mode, localName)
    }

    override fun stopAdvertising() {
        val ad = advertiser ?: return
        val cb = advertiseCallback ?: return
        try {
            ad.stopAdvertising(cb)
        } catch (e: SecurityException) {
            Timber.w(e, "stopAdvertising failed")
        } finally {
            advertiseCallback = null
        }
    }

    override fun sendSakeNotification(payload: ByteArray): Boolean {
        val server = gattServer
        val characteristic = sakeCharacteristic
        val target = peer
        if (server == null || characteristic == null || target == null) {
            Timber.w("Cannot notify SAKE: server/characteristic/peer not ready")
            return false
        }
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                server.notifyCharacteristicChanged(target, characteristic, false, payload) ==
                    BluetoothStatusCodes.SUCCESS
            } else {
                @Suppress("DEPRECATION")
                characteristic.value = payload
                @Suppress("DEPRECATION")
                server.notifyCharacteristicChanged(target, characteristic, false)
            }
        } catch (e: SecurityException) {
            Timber.w(e, "SAKE notification failed")
            false
        }
    }

    override fun connectedDevice(): BluetoothDevice? = peer

    override fun removeBond(address: String): Boolean {
        val device = adapter?.getRemoteDevice(address) ?: return false
        if (device.bondState != BluetoothDevice.BOND_BONDED) return false
        return try {
            // BluetoothDevice.removeBond() is a hidden API; reflection is the standard workaround.
            val method = device.javaClass.getMethod("removeBond")
            (method.invoke(device) as? Boolean) ?: false
        } catch (e: Exception) {
            // Do not log the MAC at WARN -- WARN+ is Sentry-eligible and the address is a device id.
            Timber.w(e, "removeBond failed")
            false
        }
    }

    override fun stop() {
        stopAdvertising()
        peer = null
        sakeCharacteristic = null
        pendingAdvertise = null
        pendingServices.clear()
        gattServer?.let {
            try {
                it.close()
            } catch (e: SecurityException) {
                Timber.w(e, "closing GATT server failed")
            }
        }
        gattServer = null
    }

    // -- Advertising --------------------------------------------------------

    private fun startAdvertising(mode: AdvertisingMode, localName: String) {
        val ad = adapter?.bluetoothLeAdvertiser
        if (ad == null) {
            Timber.e("BluetoothLeAdvertiser unavailable")
            listener?.onAdvertiseFailed(ADVERTISER_UNAVAILABLE)
            return
        }
        advertiser = ad

        // Reconnect uses a low-latency (short) interval because the paired pump scans infrequently
        // and misses long intervals (Sec. 7); first pairing uses the balanced interval.
        val advertiseMode = when (mode) {
            AdvertisingMode.RECONNECT -> AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY
            AdvertisingMode.FIRST_PAIR -> AdvertiseSettings.ADVERTISE_MODE_BALANCED
        }
        val settings = AdvertiseSettings.Builder()
            .setAdvertiseMode(advertiseMode)
            .setConnectable(true)
            .setTimeout(0) // advertise until explicitly stopped
            .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_MEDIUM)
            .build()

        // The "Mobile …" name is carried in the manufacturer data (company 0x01F9), mirroring the
        // proven JavaPumpConnector advertisement; the GAP device name is intentionally excluded to
        // keep the 31-byte advertisement within budget. Pump-side name matching is confirmed live in
        // 48.A2 (Sec. 3).
        val serviceUuid = ParcelUuid(MedtronicProtocol.sigUuid(mode.serviceUuid16))
        val data = AdvertiseData.Builder()
            .addManufacturerData(MedtronicProtocol.COMPANY_ID, MedtronicProtocol.manufacturerData(localName))
            .addServiceUuid(serviceUuid)
            .setIncludeDeviceName(false)
            .setIncludeTxPowerLevel(true)
            .build()

        val callback = object : AdvertiseCallback() {
            override fun onStartSuccess(settingsInEffect: AdvertiseSettings) {
                Timber.d("Advertising started: %s", settingsInEffect)
                listener?.onAdvertiseStarted(mode)
            }

            override fun onStartFailure(errorCode: Int) {
                Timber.e("Advertising failed: errorCode=%d", errorCode)
                listener?.onAdvertiseFailed(errorCode)
            }
        }
        advertiseCallback = callback
        try {
            ad.startAdvertising(settings, data, callback)
        } catch (e: SecurityException) {
            Timber.e(e, "startAdvertising failed")
            advertiseCallback = null
            listener?.onAdvertiseFailed(ADVERTISER_UNAVAILABLE)
        }
    }

    // -- GATT server --------------------------------------------------------

    private fun openGattServer() {
        val manager = bluetoothManager ?: run {
            Timber.e("BluetoothManager unavailable; cannot open GATT server")
            failPendingAdvertise()
            return
        }
        try {
            val server = manager.openGattServer(appContext, gattServerCallback) ?: run {
                Timber.e("openGattServer returned null")
                failPendingAdvertise()
                return
            }
            gattServer = server
            pendingServices.clear()
            pendingServices.add(createDeviceInfoService())
            pendingServices.add(createSakeService())
            addNextService()
        } catch (e: SecurityException) {
            // Missing BLUETOOTH_CONNECT: surface it instead of leaving the manager hung in CONNECTING.
            Timber.e(e, "Failed to open GATT server")
            failPendingAdvertise()
        }
    }

    private fun failPendingAdvertise() {
        pendingAdvertise = null
        listener?.onAdvertiseFailed(GATT_SERVER_UNAVAILABLE)
    }

    private fun addNextService() {
        val server = gattServer ?: return
        val next = pendingServices.poll()
        if (next == null) {
            // All services registered -- now it is safe to advertise (see start()).
            pendingAdvertise?.let { (mode, name) ->
                pendingAdvertise = null
                startAdvertising(mode, name)
            }
            return
        }
        try {
            server.addService(next)
        } catch (e: SecurityException) {
            Timber.e(e, "addService failed for %s", next.uuid)
            failPendingAdvertise()
        }
    }

    private fun createSakeService(): BluetoothGattService {
        val service = BluetoothGattService(
            MedtronicProtocol.SAKE_SERVICE_FIRST_PAIR_UUID,
            BluetoothGattService.SERVICE_TYPE_PRIMARY,
        )
        // SAKE characteristic: NOTIFY (phone -> pump) + WRITE (pump -> phone). Read-only data path;
        // no control/calibration characteristic is ever exposed. The UUID is on the Medtronic vendor
        // base (same 0xFE82 short code as the SIG-based service) to match JavaPumpConnector, which
        // paired on real hardware; the SIG-based form shipped before left the pump unable to find the
        // characteristic, so the handshake never began (issue #844). Live re-confirmation on a real
        // 780G is still pending (DESK).
        val sake = BluetoothGattCharacteristic(
            MedtronicProtocol.SAKE_CHARACTERISTIC_UUID,
            BluetoothGattCharacteristic.PROPERTY_NOTIFY or BluetoothGattCharacteristic.PROPERTY_WRITE,
            BluetoothGattCharacteristic.PERMISSION_WRITE,
        )
        sake.addDescriptor(
            BluetoothGattDescriptor(
                MedtronicProtocol.CCCD_UUID,
                BluetoothGattDescriptor.PERMISSION_READ or BluetoothGattDescriptor.PERMISSION_WRITE,
            ),
        )
        service.addCharacteristic(sake)
        sakeCharacteristic = sake
        return service
    }

    private fun createDeviceInfoService(): BluetoothGattService {
        val service = BluetoothGattService(
            MedtronicProtocol.DEVICE_INFO_SERVICE_UUID,
            BluetoothGattService.SERVICE_TYPE_PRIMARY,
        )
        fun readChar(uuid: java.util.UUID, value: ByteArray): BluetoothGattCharacteristic =
            BluetoothGattCharacteristic(
                uuid,
                BluetoothGattCharacteristic.PROPERTY_READ,
                BluetoothGattCharacteristic.PERMISSION_READ,
            ).apply { @Suppress("DEPRECATION") setValue(value) }

        // Placeholder DIS values: the read-only handshake authenticates at the app layer (SAKE), not
        // off these fields. The characteristic *set* mirrors JavaPumpConnector (including Hardware
        // Revision and the empty Regulatory Certification list) so a pump that enumerates DIS
        // membership during discovery sees the same table. JavaPumpConnector spoofs a realistic
        // app-version string; TODO(48.A2): confirm a real pump does not validate any DIS field value.
        val ascii = Charsets.US_ASCII
        service.addCharacteristic(readChar(MedtronicProtocol.MANUFACTURER_NAME_UUID, "GlycemicGPT".toByteArray(ascii)))
        service.addCharacteristic(readChar(MedtronicProtocol.MODEL_NUMBER_UUID, "Mobile".toByteArray(ascii)))
        service.addCharacteristic(readChar(MedtronicProtocol.SERIAL_NUMBER_UUID, currentName.toByteArray(ascii)))
        service.addCharacteristic(readChar(MedtronicProtocol.HARDWARE_REVISION_UUID, "0".toByteArray(ascii)))
        service.addCharacteristic(readChar(MedtronicProtocol.FIRMWARE_REVISION_UUID, "0".toByteArray(ascii)))
        service.addCharacteristic(readChar(MedtronicProtocol.SOFTWARE_REVISION_UUID, "0".toByteArray(ascii)))
        service.addCharacteristic(readChar(MedtronicProtocol.SYSTEM_ID_UUID, ByteArray(8)))
        service.addCharacteristic(readChar(MedtronicProtocol.PNP_ID_UUID, ByteArray(7)))
        service.addCharacteristic(readChar(MedtronicProtocol.REGULATORY_CERT_UUID, ByteArray(0)))
        return service
    }

    private val gattServerCallback = object : BluetoothGattServerCallback() {
        override fun onConnectionStateChange(device: BluetoothDevice, status: Int, newState: Int) {
            when (newState) {
                BluetoothProfile.STATE_CONNECTED -> {
                    peer = device
                    listener?.onPumpConnected(device.address)
                }
                BluetoothProfile.STATE_DISCONNECTED -> {
                    peer = null
                    listener?.onPumpDisconnected(status)
                }
            }
        }

        override fun onServiceAdded(status: Int, service: BluetoothGattService) {
            if (status == BluetoothGatt.GATT_SUCCESS) {
                addNextService()
            } else {
                // Without this the manager would hang in CONNECTING -- service registration is the one
                // BLE step with no timeout in this layer.
                Timber.e("Failed to add service %s (status=%d)", service.uuid, status)
                failPendingAdvertise()
            }
        }

        override fun onCharacteristicReadRequest(
            device: BluetoothDevice,
            requestId: Int,
            offset: Int,
            characteristic: BluetoothGattCharacteristic,
        ) {
            @Suppress("DEPRECATION")
            respondWithStoredBlob(device, requestId, offset, characteristic.value ?: ByteArray(0))
        }

        override fun onCharacteristicWriteRequest(
            device: BluetoothDevice,
            requestId: Int,
            characteristic: BluetoothGattCharacteristic,
            preparedWrite: Boolean,
            responseNeeded: Boolean,
            offset: Int,
            value: ByteArray,
        ) {
            if (characteristic.uuid == MedtronicProtocol.SAKE_CHARACTERISTIC_UUID) {
                listener?.onSakeWrite(value)
            }
            if (responseNeeded) {
                sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, offset, value)
            }
        }

        override fun onDescriptorReadRequest(
            device: BluetoothDevice,
            requestId: Int,
            offset: Int,
            descriptor: BluetoothGattDescriptor,
        ) {
            // Android peripherals get no auto-response, so any descriptor read the pump issues (the
            // SAKE CCCD around subscribe is the only descriptor this GATT table exposes) stalls unless
            // we answer it. The descriptor's stored value (default 0x0000 = notifications off) is the
            // correct reply for any descriptor, so this stays intentionally ungated -- unlike the CCCD
            // write handler below (issue #844; JavaPumpConnector's BlePeripheralDevice answers the same).
            @Suppress("DEPRECATION")
            respondWithStoredBlob(device, requestId, offset, descriptor.value ?: byteArrayOf(0x00, 0x00))
        }

        override fun onDescriptorWriteRequest(
            device: BluetoothDevice,
            requestId: Int,
            descriptor: BluetoothGattDescriptor,
            preparedWrite: Boolean,
            responseNeeded: Boolean,
            offset: Int,
            value: ByteArray,
        ) {
            val isSakeCccd = descriptor.uuid == MedtronicProtocol.CCCD_UUID &&
                descriptor.characteristic?.uuid == MedtronicProtocol.SAKE_CHARACTERISTIC_UUID
            if (isSakeCccd && value.size >= 2) {
                when {
                    (value[0].toInt() and 0x01) != 0 -> {
                        Timber.d("Pump subscribed to SAKE notifications")
                        listener?.onSakeSubscribed()
                    }
                    value[0].toInt() == 0 && value[1].toInt() == 0 -> {
                        Timber.d("Pump unsubscribed from SAKE notifications")
                        listener?.onSakeUnsubscribed()
                    }
                    else -> Timber.d("Unexpected SAKE CCCD value %02x%02x; ignoring", value[1], value[0])
                }
            }
            @Suppress("DEPRECATION")
            descriptor.value = value
            if (responseNeeded) {
                sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, offset, value)
            }
        }

        override fun onMtuChanged(device: BluetoothDevice, mtu: Int) {
            // We never request a larger MTU and keep every PDU <= 20 bytes regardless of what the
            // central negotiates (Sec. 6). This is observational only.
            Timber.d("Central negotiated MTU=%d (ignored; PDUs stay <= %d bytes)", mtu, PduFramer.MAX_PDU_SIZE)
        }
    }

    private fun sendResponse(device: BluetoothDevice, requestId: Int, status: Int, offset: Int, value: ByteArray) {
        try {
            gattServer?.sendResponse(device, requestId, status, offset, value)
        } catch (e: SecurityException) {
            Timber.w(e, "sendResponse failed")
        }
    }

    /** Reply to a characteristic or descriptor read with [stored], honoring the central's [offset]. */
    private fun respondWithStoredBlob(device: BluetoothDevice, requestId: Int, offset: Int, stored: ByteArray) {
        // The ATT offset is an unsigned 16-bit field, so a negative value can't arrive from the wire;
        // the `offset < 0` guard is defensive so copyOfRange() below can never throw.
        if (offset < 0 || offset > stored.size) {
            sendResponse(device, requestId, BluetoothGatt.GATT_INVALID_OFFSET, offset, ByteArray(0))
            return
        }
        sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, offset, stored.copyOfRange(offset, stored.size))
    }

    private companion object {
        /** Synthetic AdvertiseCallback error code for "no advertiser available" (not a platform code). */
        const val ADVERTISER_UNAVAILABLE = -1

        /** Synthetic error code for "GATT server could not be opened" (e.g. missing permission). */
        const val GATT_SERVER_UNAVAILABLE = -2
    }
}
