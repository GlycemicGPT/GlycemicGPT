package com.glycemicgpt.mobile.ble.connection

import android.annotation.SuppressLint
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.content.Context
import android.os.Build
import com.glycemicgpt.mobile.ble.auth.JpakeAuthenticator
import com.glycemicgpt.mobile.ble.auth.TandemAuthenticator
import com.glycemicgpt.mobile.ble.protocol.PacketAssembler
import com.glycemicgpt.mobile.ble.protocol.Packetize
import com.glycemicgpt.mobile.ble.protocol.TandemProtocol
import com.glycemicgpt.mobile.domain.pump.DebugLogger
import com.glycemicgpt.mobile.domain.pump.PumpCredentialProvider
import com.glycemicgpt.mobile.domain.pump.toSpacedHex
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.pump.PumpConnectionManager
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import timber.log.Timber
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.TimeoutException
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Manages the BLE connection lifecycle to a Tandem pump.
 *
 * Responsibilities:
 * - Connect to a pump by address
 * - Negotiate MTU and enable GATT notifications (serialized via operation queue)
 * - Run the authentication handshake
 * - Auto-reconnect with exponential backoff
 * - Expose connection state as a Flow
 */
@Singleton
class BleConnectionManager @Inject constructor(
    @ApplicationContext private val context: Context,
    private val authenticator: TandemAuthenticator,
    private val jpakeAuthenticator: JpakeAuthenticator,
    private val credentialStore: PumpCredentialProvider,
    private val debugLogger: DebugLogger,
) : PumpConnectionManager {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val bluetoothManager: BluetoothManager? =
        context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager

    private val _connectionState = MutableStateFlow(ConnectionState.DISCONNECTED)
    override val connectionState: StateFlow<ConnectionState> = _connectionState.asStateFlow()

    private var gatt: BluetoothGatt? = null
    private val gattLock = Any()
    private val txId = AtomicInteger(0)
    private val assemblers = ConcurrentHashMap<UUID, PacketAssembler>()

    @Volatile
    private var reconnectAttempt = 0
    @Volatile
    private var reconnectJob: Job? = null
    @Volatile
    private var autoReconnect = true
    @Volatile
    private var reconnectPhase = ReconnectPhase.FAST
    // Passive autoConnect=true GATT for slow-phase reconnection.
    // Android's BLE stack handles reconnection in the kernel when the device
    // comes back in range, without requiring CPU wake or polling.
    @Volatile
    private var autoConnectGatt: BluetoothGatt? = null
    private val autoConnectLock = Any()

    // Tracks rapid disconnections after connect (bond loss detection).
    // If the pump disconnects us multiple times before we ever reach CONNECTED,
    // it likely means the BLE bond was lost and re-pairing is required.
    @Volatile
    private var rapidDisconnectCount = 0

    // Tracks connections where we reach CONNECTED but receive zero notifications.
    // If this happens repeatedly, the pump is not responding (likely needs re-pairing).
    @Volatile
    private var zeroResponseConnectionCount = 0
    // Tracks consecutive INSUFFICIENT_ENCRYPTION disconnects (during active sessions
    // or reconnection attempts after a prior successful session).
    // After MAX_ENCRYPTION_FAILURES, the bond is considered genuinely stale.
    @Volatile
    private var encryptionFailureCount = 0
    @Volatile
    private var receivedAnyNotification = false

    // Tracks whether we have ever reached CONNECTED+authenticated in this
    // service session. Distinguishes idle-timeout disconnects (status 19
    // after a prior successful session) from genuine bond-loss disconnects
    // (status 19 when the pump has never accepted our connection).
    // Reset only on user-initiated disconnect() or unpair(), NOT on connect()
    // so it survives reconnect cycles.
    @Volatile
    private var hadSuccessfulSession = false

    // Tracks consecutive reconnect failures (auth timeout, status 19, etc.)
    // even when hadSuccessfulSession is true. If the pump genuinely loses its
    // bond mid-session (factory reset, battery pull), we need a fallback to
    // detect this and stop futile reconnection attempts.
    @Volatile
    private var consecutiveReconnectFailures = 0

    // GATT operation queue -- only one GATT write at a time
    private val operationQueue = ConcurrentLinkedQueue<GattOperation>()
    private val operationInFlight = AtomicBoolean(false)

    // Pending notification subscriptions to serialize after service discovery
    private var pendingNotificationUuids = listOf<UUID>()

    // Pending pairing code provided by the user during initial pairing
    @Volatile
    private var pendingPairingCode: String? = null

    // Pending status read requests: txId -> deferred response cargo
    private val pendingRequests = ConcurrentHashMap<Int, CompletableDeferred<ByteArray>>()

    // FFF8 history log stream: collects multi-packet notifications after opcode 60.
    // The pump sends N independent Tandem-framed packets on FFF8, each containing
    // a few records. We accumulate all packet cargos and complete the deferred
    // after an idle timeout (pump stops sending).
    private val historyLogAssembler = PacketAssembler()
    @Volatile
    private var historyLogDeferred: CompletableDeferred<List<ByteArray>>? = null
    private val historyLogBuffer = mutableListOf<ByteArray>()
    @Volatile
    private var historyLogIdleJob: Job? = null

    // Handshake timeout: fail if authentication doesn't complete within this window.
    // JPAKE has 5 round trips; 30s is generous even on slow BLE connections.
    private var authTimeoutJob: Job? = null

    // Post-auth settle: delayed job that sets CONNECTED after the pump stabilizes.
    // Must be cancelled on disconnect to prevent stale CONNECTED state.
    private var settleJob: Job? = null

    private sealed class GattOperation {
        data class WriteCharacteristic(
            val characteristicUuid: UUID,
            val data: ByteArray,
        ) : GattOperation()

        data class WriteDescriptor(
            val characteristicUuid: UUID,
        ) : GattOperation()
    }

    /**
     * Connect to the pump at [address].
     *
     * Resets reconnect attempt and error counters so the connection starts fresh.
     */
    override fun connect(address: String, pairingCode: String?) {
        connectInternal(address, pairingCode, resetCounters = true)
    }

    /**
     * Internal connect implementation.
     *
     * @param resetCounters If true, resets reconnect attempt and error counters.
     *   Set to false when called from [scheduleReconnect] or the passive autoConnect
     *   GATT callback to preserve exponential backoff across reconnection cycles.
     */
    @SuppressLint("MissingPermission")
    private fun connectInternal(address: String, pairingCode: String?, resetCounters: Boolean) {
        val adapter = bluetoothManager?.adapter ?: run {
            Timber.e("BluetoothAdapter not available")
            return
        }

        val device: BluetoothDevice = adapter.getRemoteDevice(address)
        val bondState = device.bondState
        Timber.d("Bond state for %s: %s", address, when (bondState) {
            BluetoothDevice.BOND_NONE -> "NONE"
            BluetoothDevice.BOND_BONDING -> "BONDING"
            BluetoothDevice.BOND_BONDED -> "BONDED"
            else -> "UNKNOWN($bondState)"
        })
        // Cancel any pending scheduled reconnect to avoid racing with this connect
        reconnectJob?.cancel()
        reconnectJob = null
        cancelAutoConnectGatt()
        _connectionState.value = ConnectionState.CONNECTING
        autoReconnect = true
        if (resetCounters) {
            reconnectAttempt = 0
            rapidDisconnectCount = 0
            encryptionFailureCount = 0
            zeroResponseConnectionCount = 0
        }
        receivedAnyNotification = false
        pendingPairingCode = pairingCode
        authenticator.reset()
        jpakeAuthenticator.reset()
        operationQueue.clear()
        operationInFlight.set(false)
        // Clear stale packet assemblers from previous connection
        assemblers.clear()
        statusAssemblers.clear()
        cancelPendingRequests()
        // Cancel any pending history log stream request from previous connection
        cancelHistoryLogDeferred()

        Timber.d("Connecting to pump: %s", address)
        val newGatt = device.connectGatt(context, false, gattCallback, BluetoothDevice.TRANSPORT_LE)
        if (newGatt == null) {
            Timber.e("Failed to create GATT connection")
            _connectionState.value = ConnectionState.DISCONNECTED
            return
        }
        synchronized(gattLock) {
            gatt = newGatt
        }
    }

    /** Disconnect from the pump. */
    @SuppressLint("MissingPermission")
    override fun disconnect() {
        autoReconnect = false
        hadSuccessfulSession = false
        reconnectJob?.cancel()
        reconnectJob = null
        cancelAutoConnectGatt()
        authTimeoutJob?.cancel()
        authTimeoutJob = null
        settleJob?.cancel()
        settleJob = null
        operationQueue.clear()
        operationInFlight.set(false)
        cancelPendingRequests()
        cancelHistoryLogDeferred()
        synchronized(gattLock) {
            gatt?.let {
                Timber.d("Disconnecting from pump")
                it.disconnect()
                it.close()
            }
            gatt = null
        }
        _connectionState.value = ConnectionState.DISCONNECTED
    }

    private fun cancelPendingRequests() {
        // Atomically drain: remove each entry individually to avoid
        // race with concurrent sendStatusRequest insertions
        val iter = pendingRequests.entries.iterator()
        while (iter.hasNext()) {
            val entry = iter.next()
            iter.remove()
            entry.value.cancel()
        }
    }

    /** Cancel any pending history log stream request and reset the assembler. */
    private fun cancelHistoryLogDeferred() {
        historyLogIdleJob?.cancel()
        historyLogIdleJob = null
        historyLogDeferred?.cancel()
        historyLogDeferred = null
        synchronized(historyLogAssembler) {
            historyLogAssembler.reset()
            historyLogBuffer.clear()
        }
    }

    /** Unpair: clear credentials, remove BLE bond, and disconnect. */
    @SuppressLint("MissingPermission")
    override fun unpair() {
        val address = credentialStore.getPairedAddress()
        disconnect()
        credentialStore.clearPairing()
        // Remove the BLE bond so stale encryption keys don't block future connections.
        if (address != null) {
            removeBond(address)
        }
        cancelAutoConnectGatt()
        Timber.d("Pump unpaired, credentials + JPAKE session cleared, bond removed")
    }

    /**
     * Remove the BLE bond for a device by address.
     * Uses reflection because BluetoothDevice.removeBond() is a hidden API.
     */
    @SuppressLint("MissingPermission")
    private fun removeBond(address: String) {
        try {
            val adapter = bluetoothManager?.adapter ?: return
            val device = adapter.getRemoteDevice(address)
            if (device.bondState == BluetoothDevice.BOND_BONDED) {
                val method = device.javaClass.getMethod("removeBond")
                val result = method.invoke(device) as? Boolean ?: false
                Timber.d("removeBond(%s) = %b", address, result)
            }
        } catch (e: Exception) {
            Timber.w(e, "Failed to remove BLE bond for %s", address)
        }
    }

    /**
     * Clear Android's GATT service cache via reflection.
     * This forces a fresh service discovery, preventing stale cached
     * characteristics from silently dropping notifications.
     */
    private fun refreshGattCache(gatt: BluetoothGatt) {
        try {
            val method = gatt.javaClass.getMethod("refresh")
            val result = method.invoke(gatt) as? Boolean ?: false
            Timber.d("GATT cache refresh = %b", result)
        } catch (e: Exception) {
            Timber.w(e, "Failed to refresh GATT cache")
        }
    }

    /** Attempt auto-reconnect to the previously paired pump. */
    override fun autoReconnectIfPaired() {
        val address = credentialStore.getPairedAddress() ?: return
        // Fresh reconnect: reset to fast phase (called from BT state receiver,
        // service startup, etc. -- these are all "new" reconnection attempts).
        synchronized(autoConnectLock) {
            reconnectPhase = ReconnectPhase.FAST
        }
        cancelAutoConnectGatt()
        // Pass null for pairingCode -- reconnects use JPAKE confirmation mode
        // with the saved derived secret from initial pairing.
        connect(address, pairingCode = null)
    }

    /**
     * Send a status read request and wait for the response cargo.
     *
     * @param opcode The read-only status request opcode.
     * @param cargo Request payload (empty for most status reads).
     * @param timeoutMs Maximum time to wait for a response.
     * @return The response cargo bytes.
     * @throws TimeoutException if no response within [timeoutMs].
     * @throws IllegalStateException if not connected.
     */
    suspend fun sendStatusRequest(
        opcode: Int,
        cargo: ByteArray = ByteArray(0),
        timeoutMs: Long = TandemProtocol.STATUS_READ_TIMEOUT_MS,
    ): ByteArray {
        if (_connectionState.value != ConnectionState.CONNECTED) {
            throw IllegalStateException("Not connected to pump")
        }

        val id = nextTxId()
        val deferred = CompletableDeferred<ByteArray>()

        // Evict any stale deferred with the same txId (wraps at 256)
        val evicted = pendingRequests.put(id, deferred)
        if (evicted != null) {
            Timber.w("Evicting stale pending request txId=%d", id)
            evicted.cancel()
        }

        Timber.d("BLE_RAW TX opcode=0x%02x txId=%d cargoLen=%d", opcode, id, cargo.size)
        debugLogger.logPacket(
            direction = DebugLogger.Direction.TX,
            opcode = opcode,
            opcodeName = TandemProtocol.opcodeName(opcode),
            txId = id,
            cargoHex = cargo.toSpacedHex(),
            cargoSize = cargo.size,
        )

        val chunks = Packetize.encode(opcode, id, cargo, TandemProtocol.CHUNK_SIZE_SHORT)
        enqueueWrite(TandemProtocol.CURRENT_STATUS_UUID, chunks)

        return try {
            withTimeout(timeoutMs) {
                deferred.await()
            }
        } finally {
            // Always clean up -- whether completed, timed out, or cancelled
            pendingRequests.remove(id, deferred)
        }
    }

    /**
     * Send an opcode 60 (HistoryLogRequest) on FFF6 and collect the response
     * that arrives on FFF8 (HISTORY_LOG_UUID).
     *
     * The pump responds with a 2-byte ACK on FFF6 and streams actual records
     * on FFF8. This method ignores the FFF6 ACK and waits for the FFF8 data.
     *
     * @param cargo 5-byte opcode 60 cargo (uint32 LE startIndex + byte count)
     * @param timeoutMs max time to wait for FFF8 response
     * @return list of individual FFF8 packet cargos (each with optional 2-byte header + 26-byte records)
     */
    suspend fun requestHistoryLogStream(
        cargo: ByteArray,
        timeoutMs: Long = TandemProtocol.HISTORY_LOG_TIMEOUT_MS,
    ): List<ByteArray> {
        if (_connectionState.value != ConnectionState.CONNECTED) {
            throw IllegalStateException("Not connected to pump")
        }

        val deferred = CompletableDeferred<List<ByteArray>>()
        // Reset assembler, buffer, and set deferred atomically so FFF8
        // notifications can't feed stale data or find a null deferred.
        synchronized(historyLogAssembler) {
            historyLogAssembler.reset()
            historyLogBuffer.clear()
            historyLogIdleJob?.cancel()
            historyLogDeferred = deferred
        }

        // Send opcode 60 on FFF6. The FFF6 response is a 2-byte ACK which
        // sendStatusRequest will return. We ignore it.
        val id = nextTxId()
        val ackDeferred = CompletableDeferred<ByteArray>()
        pendingRequests.put(id, ackDeferred)?.cancel()

        Timber.d("BLE_RAW TX opcode=0x%02x txId=%d cargoLen=%d (history log request)",
            TandemProtocol.OPCODE_HISTORY_LOG_REQ, id, cargo.size)
        debugLogger.logPacket(
            direction = DebugLogger.Direction.TX,
            opcode = TandemProtocol.OPCODE_HISTORY_LOG_REQ,
            opcodeName = TandemProtocol.opcodeName(TandemProtocol.OPCODE_HISTORY_LOG_REQ),
            txId = id,
            cargoHex = cargo.toSpacedHex(),
            cargoSize = cargo.size,
        )

        val chunks = Packetize.encode(
            TandemProtocol.OPCODE_HISTORY_LOG_REQ, id, cargo,
            TandemProtocol.CHUNK_SIZE_SHORT,
        )
        enqueueWrite(TandemProtocol.CURRENT_STATUS_UUID, chunks)

        return try {
            // Wait for FFF8 packets (ignore FFF6 ACK)
            withTimeout(timeoutMs) {
                deferred.await()
            }
        } finally {
            historyLogIdleJob?.cancel()
            historyLogIdleJob = null
            historyLogDeferred = null
            pendingRequests.remove(id, ackDeferred)
        }
    }

    private fun nextTxId(): Int = txId.getAndIncrement() and 0xFF

    /** Enqueue a characteristic write for serialized GATT execution. */
    private fun enqueueWrite(characteristicUuid: UUID, chunks: List<ByteArray>) {
        for (chunk in chunks) {
            operationQueue.add(GattOperation.WriteCharacteristic(characteristicUuid, chunk))
        }
        drainOperationQueue()
    }

    /** Enqueue a descriptor write (notification enable) for serialized execution. */
    private fun enqueueNotificationEnable(characteristicUuid: UUID) {
        operationQueue.add(GattOperation.WriteDescriptor(characteristicUuid))
        drainOperationQueue()
    }

    @SuppressLint("MissingPermission")
    private fun drainOperationQueue() {
        if (!operationInFlight.compareAndSet(false, true)) return
        val op = operationQueue.poll()
        if (op == null) {
            operationInFlight.set(false)
            return
        }

        val currentGatt = synchronized(gattLock) { gatt }
        if (currentGatt == null) {
            Timber.w("GATT null, dropping operation")
            operationInFlight.set(false)
            operationQueue.clear()
            return
        }

        when (op) {
            is GattOperation.WriteCharacteristic -> {
                val service = currentGatt.getService(TandemProtocol.PUMP_SERVICE_UUID)
                val characteristic = service?.getCharacteristic(op.characteristicUuid)
                if (characteristic == null) {
                    Timber.e("Characteristic %s not found", op.characteristicUuid)
                    operationInFlight.set(false)
                    drainOperationQueue()
                    return
                }
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    currentGatt.writeCharacteristic(
                        characteristic,
                        op.data,
                        BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT,
                    )
                } else {
                    @Suppress("DEPRECATION")
                    characteristic.value = op.data
                    @Suppress("DEPRECATION")
                    characteristic.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
                    @Suppress("DEPRECATION")
                    currentGatt.writeCharacteristic(characteristic)
                }
            }
            is GattOperation.WriteDescriptor -> {
                val service = currentGatt.getService(TandemProtocol.PUMP_SERVICE_UUID)
                val characteristic = service?.getCharacteristic(op.characteristicUuid)
                if (characteristic == null) {
                    operationInFlight.set(false)
                    drainOperationQueue()
                    return
                }
                currentGatt.setCharacteristicNotification(characteristic, true)
                val descriptor = characteristic.getDescriptor(TandemProtocol.CCCD_UUID)
                if (descriptor == null) {
                    operationInFlight.set(false)
                    drainOperationQueue()
                    return
                }
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    currentGatt.writeDescriptor(
                        descriptor,
                        BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE,
                    )
                } else {
                    @Suppress("DEPRECATION")
                    descriptor.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                    @Suppress("DEPRECATION")
                    currentGatt.writeDescriptor(descriptor)
                }
            }
        }
    }

    private fun onGattOperationComplete() {
        operationInFlight.set(false)
        drainOperationQueue()
    }

    /**
     * Schedule the next reconnection attempt using a tiered strategy:
     *
     * **FAST phase:** Exponential backoff 1s -> 32s for the first
     * [MAX_FAST_RECONNECT_ATTEMPTS] attempts (~5 minutes). Suitable for
     * transient radio interference or momentary pump distance.
     *
     * **SLOW phase:** Periodic attempts every [SLOW_RECONNECT_INTERVAL_MS]
     * (2 minutes) indefinitely. Also opens a passive `autoConnect=true` GATT
     * connection so Android's BLE stack can reconnect immediately when the
     * pump comes back in range (runs in kernel, no CPU wake needed).
     *
     * The pump is a medical device -- if the user hasn't explicitly unpaired,
     * we should always try to reconnect. Bond-loss detection (insufficient
     * auth, insufficient encryption, rapid disconnects, zero-response) still
     * triggers AUTH_FAILED when appropriate.
     */
    private fun scheduleReconnect() {
        if (!autoReconnect) return
        val address = credentialStore.getPairedAddress() ?: return

        _connectionState.value = ConnectionState.RECONNECTING

        // Synchronize phase transitions to prevent races with autoReconnectIfPaired()
        // or onAuthSuccess() resetting the phase from another thread.
        val delayMs: Long
        synchronized(autoConnectLock) {
            if (reconnectPhase == ReconnectPhase.FAST) {
                reconnectAttempt = minOf(reconnectAttempt + 1, MAX_FAST_RECONNECT_ATTEMPTS)
                if (reconnectAttempt >= MAX_FAST_RECONNECT_ATTEMPTS) {
                    // Transition to slow phase -- start passive autoConnect GATT
                    reconnectPhase = ReconnectPhase.SLOW
                    Timber.d("Fast reconnect exhausted (%d attempts), switching to slow phase", reconnectAttempt)
                    startAutoConnectGatt(address)
                    delayMs = SLOW_RECONNECT_INTERVAL_MS
                } else {
                    delayMs = minOf(1000L * (1 shl minOf(reconnectAttempt, 5)), 32_000L)
                    Timber.d("Fast reconnect attempt %d in %d ms", reconnectAttempt, delayMs)
                }
            } else {
                // SLOW phase: periodic attempts every 2 minutes with autoConnect=true
                // as a passive supplement. The autoConnect GATT runs in the kernel BLE
                // stack and triggers immediately when the device comes back in range.
                // The periodic timer is a fallback for devices with buggy autoConnect.
                Timber.d("Slow reconnect: next attempt in %d ms", SLOW_RECONNECT_INTERVAL_MS)
                // Ensure autoConnect GATT is open (may have been closed by a connect attempt)
                startAutoConnectGatt(address)
                delayMs = SLOW_RECONNECT_INTERVAL_MS
            }
        }

        reconnectJob = scope.launch {
            delay(delayMs)
            if (autoReconnect && _connectionState.value == ConnectionState.RECONNECTING) {
                connectInternal(address, pairingCode = null, resetCounters = false)
            } else if (_connectionState.value == ConnectionState.RECONNECTING) {
                _connectionState.value = ConnectionState.DISCONNECTED
            }
        }
    }

    /** Open a passive autoConnect=true GATT connection for background reconnection. */
    @SuppressLint("MissingPermission")
    private fun startAutoConnectGatt(address: String) {
        synchronized(autoConnectLock) {
            if (autoConnectGatt != null) return // already open
            val adapter = bluetoothManager?.adapter ?: run {
                Timber.w("Cannot open autoConnect GATT: BluetoothAdapter not available")
                return
            }
            val device = adapter.getRemoteDevice(address)
            Timber.d("Opening autoConnect=true GATT for passive reconnection")
            autoConnectGatt = device.connectGatt(context, true, autoConnectCallback, BluetoothDevice.TRANSPORT_LE)
        }
    }

    /** Close the passive autoConnect GATT if open. */
    @SuppressLint("MissingPermission")
    private fun cancelAutoConnectGatt() {
        synchronized(autoConnectLock) {
            autoConnectGatt?.let {
                it.disconnect()
                it.close()
                Timber.d("autoConnect GATT cancelled")
            }
            autoConnectGatt = null
        }
    }

    @SuppressLint("MissingPermission")
    private val autoConnectCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED && status == BluetoothGatt.GATT_SUCCESS) {
                Timber.d("autoConnect GATT triggered -- device back in range, initiating full connect")
                // Close the auto-connect GATT -- we'll open a proper one via connect()
                synchronized(autoConnectLock) {
                    gatt.disconnect()
                    gatt.close()
                    autoConnectGatt = null
                }
                // Post to coroutine scope: connect() performs GATT operations that must
                // not run on the binder thread delivering this callback.
                scope.launch {
                    reconnectJob?.cancel()
                    val address = credentialStore.getPairedAddress() ?: return@launch
                    connectInternal(address, pairingCode = null, resetCounters = false)
                }
            } else if (newState == BluetoothProfile.STATE_CONNECTED) {
                // Connected but with non-success status -- close and let autoConnect retry
                Timber.w("autoConnect GATT connected with error status=%d, closing", status)
                synchronized(autoConnectLock) {
                    gatt.disconnect()
                    gatt.close()
                    autoConnectGatt = null
                }
            }
            // STATE_DISCONNECTED: autoConnect will keep retrying in the BLE stack
        }
    }

    @SuppressLint("MissingPermission")
    private val gattCallback = object : BluetoothGattCallback() {

        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            when (newState) {
                BluetoothProfile.STATE_CONNECTED -> {
                    // Clear GATT service cache on reconnect. Android caches GATT
                    // services after bonding; stale caches can cause notifications
                    // to silently fail on subsequent connections.
                    refreshGattCache(gatt)
                    // Request HIGH connection priority (7.5-15ms interval) to match
                    // pumpX2 behavior. The pump may drop connections with slower
                    // default intervals (~30-50ms).
                    gatt.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH)
                    Timber.d("GATT connected, requesting MTU %d (priority=HIGH)", TandemProtocol.REQUIRED_MTU)
                    gatt.requestMtu(TandemProtocol.REQUIRED_MTU)
                }
                BluetoothProfile.STATE_DISCONNECTED -> {
                    Timber.w("BLE_RAW GATT disconnected status=%d (%s)",
                        status, gattStatusName(status))
                    settleJob?.cancel()
                    settleJob = null
                    synchronized(gattLock) {
                        this@BleConnectionManager.gatt?.close()
                        this@BleConnectionManager.gatt = null
                    }
                    operationQueue.clear()
                    operationInFlight.set(false)
                    cancelPendingRequests()

                    // Bond-loss detection: if the pump keeps disconnecting us
                    // before we ever reach CONNECTED (e.g., status 5 or 19),
                    // the BLE bond is likely lost and re-pairing is needed.
                    val wasConnected = _connectionState.value == ConnectionState.CONNECTED ||
                        _connectionState.value == ConnectionState.AUTHENTICATING
                    if (!wasConnected && status == GATT_CONN_TERMINATE_PEER_USER) {
                        if (hadSuccessfulSession) {
                            // Idle-timeout during reconnection, not bond loss.
                            // The pump previously accepted our connection this session,
                            // so status 19 means it dropped idle -- not bond rejection.
                            // Let scheduleReconnect() handle the phase transition
                            // (fast -> slow) rather than giving up with AUTH_FAILED.
                            // The pump is a medical device: if the user hasn't unpaired,
                            // keep trying indefinitely.
                            consecutiveReconnectFailures = minOf(consecutiveReconnectFailures + 1, MAX_CONSECUTIVE_RECONNECT_FAILURES)
                            Timber.d("Status 19 during reconnect after prior successful session (%d/%d) -- treating as idle-timeout, continuing reconnection",
                                consecutiveReconnectFailures, MAX_FAST_RECONNECT_ATTEMPTS)
                        } else {
                            rapidDisconnectCount++
                            if (rapidDisconnectCount >= MAX_RAPID_DISCONNECTS) {
                                Timber.e("Pump rejected %d consecutive connections -- BLE bond likely lost, re-pairing required",
                                    rapidDisconnectCount)
                                autoReconnect = false
                                authTimeoutJob?.cancel()
                                reconnectJob?.cancel()
                                cancelAutoConnectGatt()
                                _connectionState.value = ConnectionState.AUTH_FAILED
                                return
                            }
                        }
                    }
                    // Insufficient authentication before CONNECTED = bond definitely lost.
                    // During an active session, status 0x05 can be transient (key rotation),
                    // so only treat it as bond loss if we haven't reached CONNECTED yet.
                    if (!wasConnected && status == GATT_INSUFFICIENT_AUTHENTICATION) {
                        Timber.e("Pump reports insufficient authentication -- BLE bond lost, re-pairing required")
                        val addr = credentialStore.getPairedAddress()
                        if (addr != null) removeBond(addr)
                        autoReconnect = false
                        rapidDisconnectCount = 0
                        authTimeoutJob?.cancel()
                        reconnectJob?.cancel()
                        cancelAutoConnectGatt()
                        _connectionState.value = ConnectionState.AUTH_FAILED
                        return
                    }
                    // Insufficient encryption handling: status 8 often means the
                    // phone woke from deep sleep and the BLE link needs to
                    // renegotiate encryption. If we had a prior successful session
                    // (hadSuccessfulSession=true), this is transient -- allow
                    // reconnect and count failures. Only declare bond loss if:
                    // (a) we never had a successful session (genuinely stale keys),
                    // or (b) MAX_ENCRYPTION_FAILURES consecutive failures.
                    if (status == GATT_INSUFFICIENT_ENCRYPTION) {
                        val wasFullyConnected = _connectionState.value == ConnectionState.CONNECTED
                        if (!wasFullyConnected && !hadSuccessfulSession) {
                            // Never had a successful session and encryption failed
                            // before reaching CONNECTED -- bond keys genuinely stale.
                            Timber.e("Pump reports insufficient encryption before connected -- bond keys stale, removing bond for re-pairing")
                            val addr = credentialStore.getPairedAddress()
                            if (addr != null) removeBond(addr)
                            autoReconnect = false
                            authTimeoutJob?.cancel()
                            reconnectJob?.cancel()
                            cancelAutoConnectGatt()
                            _connectionState.value = ConnectionState.AUTH_FAILED
                            return
                        }
                        // Either we were fully connected (active session disruption)
                        // or we had a prior successful session (transient encryption
                        // renegotiation during reconnect -- e.g., phone woke from
                        // deep sleep and BLE link key refresh failed transiently).
                        // Count failures and only give up after MAX_ENCRYPTION_FAILURES.
                        encryptionFailureCount++
                        if (encryptionFailureCount >= MAX_ENCRYPTION_FAILURES) {
                            Timber.e("Encryption failed %d consecutive times -- bond likely stale, removing for re-pairing",
                                encryptionFailureCount)
                            val addr = credentialStore.getPairedAddress()
                            if (addr != null) removeBond(addr)
                            autoReconnect = false
                            authTimeoutJob?.cancel()
                            reconnectJob?.cancel()
                            cancelAutoConnectGatt()
                            _connectionState.value = ConnectionState.AUTH_FAILED
                            return
                        }
                        if (wasFullyConnected) rapidDisconnectCount = 0
                        Timber.d("Insufficient encryption %s (%d/%d) -- reconnecting (bond preserved)",
                            if (wasFullyConnected) "during active session" else "before connected (prior session exists)",
                            encryptionFailureCount, MAX_ENCRYPTION_FAILURES)
                        // Fall through to normal disconnect/reconnect path
                    }

                    // Track connections where we reached CONNECTED but got zero
                    // notifications. This means the pump ignored all our requests,
                    // likely because it requires re-pairing.
                    if (wasConnected && !receivedAnyNotification) {
                        zeroResponseConnectionCount++
                        Timber.w("Zero-response connection #%d (pump ignoring requests)",
                            zeroResponseConnectionCount)
                        if (zeroResponseConnectionCount >= MAX_ZERO_RESPONSE_CONNECTIONS) {
                            Timber.e("Pump has not responded in %d consecutive connections -- re-pairing required",
                                zeroResponseConnectionCount)
                            val addr = credentialStore.getPairedAddress()
                            if (addr != null) removeBond(addr)
                            autoReconnect = false
                            authTimeoutJob?.cancel()
                            reconnectJob?.cancel()
                            cancelAutoConnectGatt()
                            _connectionState.value = ConnectionState.AUTH_FAILED
                            return
                        }
                    } else if (receivedAnyNotification) {
                        zeroResponseConnectionCount = 0
                    }

                    _connectionState.value = ConnectionState.DISCONNECTED
                    if (autoReconnect) scheduleReconnect()
                }
            }
        }

        override fun onMtuChanged(gatt: BluetoothGatt, mtu: Int, status: Int) {
            if (status == BluetoothGatt.GATT_SUCCESS) {
                Timber.d("MTU changed to %d, discovering services", mtu)
                gatt.discoverServices()
            } else {
                Timber.e("MTU request failed (status=%d)", status)
                synchronized(gattLock) {
                    gatt.close()
                    this@BleConnectionManager.gatt = null
                }
                operationQueue.clear()
                operationInFlight.set(false)
                _connectionState.value = ConnectionState.DISCONNECTED
            }
        }

        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            if (status != BluetoothGatt.GATT_SUCCESS) {
                Timber.e("Service discovery failed (status=%d)", status)
                return
            }

            Timber.d("Services discovered, enabling notifications")
            // Enable AUTHORIZATION CCCD first so the pump can respond to
            // JPAKE immediately. Then enqueue auth, then the remaining CCCDs.
            // This matches the pumpX2 approach: auth first, then status CCCDs.
            enqueueNotificationEnable(TandemProtocol.AUTHORIZATION_UUID)
            _connectionState.value = ConnectionState.AUTHENTICATING
            startAuthentication()
            // Enable remaining notification CCCDs after auth is queued.
            // They'll execute after JPAKE chunks in the serialized queue.
            for (uuid in TandemProtocol.NOTIFICATION_CHARACTERISTICS) {
                if (uuid != TandemProtocol.AUTHORIZATION_UUID) {
                    enqueueNotificationEnable(uuid)
                }
            }
        }

        override fun onCharacteristicWrite(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            status: Int,
        ) {
            if (status != BluetoothGatt.GATT_SUCCESS) {
                Timber.e("BLE_RAW WRITE FAILED status=%d (%s) char=%s",
                    status, gattStatusName(status), characteristic.uuid)
            } else {
                Timber.d("BLE_RAW WRITE OK char=%s", characteristic.uuid)
            }
            onGattOperationComplete()
        }

        override fun onDescriptorWrite(
            gatt: BluetoothGatt,
            descriptor: BluetoothGattDescriptor,
            status: Int,
        ) {
            val charUuid = descriptor.characteristic?.uuid
            if (status != BluetoothGatt.GATT_SUCCESS) {
                Timber.e("Descriptor write failed (status=%d, char=%s)", status, charUuid)
            } else {
                Timber.d("CCCD enabled for %s", charUuid)
            }
            onGattOperationComplete()
        }

        // API < 33 callback
        @Deprecated("Deprecated in API 33")
        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
        ) {
            @Suppress("DEPRECATION")
            val data = characteristic.value ?: return
            handleCharacteristicChanged(characteristic.uuid, data)
        }

        // API 33+ callback
        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray,
        ) {
            handleCharacteristicChanged(characteristic.uuid, value)
        }
    }

    private fun handleCharacteristicChanged(uuid: UUID, data: ByteArray) {
        receivedAnyNotification = true
        Timber.d("BLE_RAW NOTIFY char=%s len=%d", uuid, data.size)
        when (uuid) {
            TandemProtocol.AUTHORIZATION_UUID -> handleAuthNotification(data)
            TandemProtocol.CURRENT_STATUS_UUID -> handleStatusNotification(data)
            TandemProtocol.HISTORY_LOG_UUID -> handleHistoryLogNotification(data)
            else -> Timber.d("BLE_RAW NOTIFY unhandled char=%s", uuid)
        }
    }

    // Per-txId assemblers for status responses to handle interleaved
    // multi-chunk notifications from concurrent requests
    private val statusAssemblers = ConcurrentHashMap<Int, PacketAssembler>()

    private fun handleStatusNotification(data: ByteArray) {
        // Peek at the txId from the chunk header (byte 1) to route to
        // the correct per-transaction assembler
        if (data.size < 2) return
        val chunkTxId = data[1].toInt() and 0xFF

        val assembler = statusAssemblers.getOrPut(chunkTxId) { PacketAssembler() }
        val raw: ByteArray
        synchronized(assembler) {
            if (!assembler.feed(data)) return
            raw = assembler.assemble()
            assembler.reset()
        }
        statusAssemblers.remove(chunkTxId)

        val parsed = Packetize.parseHeader(raw) ?: run {
            Timber.e("Failed to parse status notification txId=%d len=%d",
                chunkTxId, raw.size)
            debugLogger.logPacket(
                direction = DebugLogger.Direction.RX,
                opcode = if (raw.isNotEmpty()) raw[0].toInt() and 0xFF else -1,
                opcodeName = "PARSE_FAIL",
                txId = chunkTxId,
                cargoHex = raw.toSpacedHex(),
                cargoSize = raw.size,
                error = "CRC or header parse failed",
            )
            return
        }

        val (opcode, responseTxId, cargo) = parsed
        val cargoHex = cargo.toSpacedHex()
        Timber.d("BLE_RAW RX opcode=0x%02x txId=%d cargoLen=%d hex=%s",
            opcode, responseTxId, cargo.size, cargoHex)
        debugLogger.logPacket(
            direction = DebugLogger.Direction.RX,
            opcode = opcode,
            opcodeName = TandemProtocol.opcodeName(opcode),
            txId = responseTxId,
            cargoHex = cargoHex,
            cargoSize = cargo.size,
        )

        val deferred = pendingRequests.remove(responseTxId)
        if (deferred != null) {
            deferred.complete(cargo)
        } else {
            Timber.w("Received unsolicited status response txId=%d opcode=0x%02x",
                responseTxId, opcode)
        }
    }

    /**
     * Handle FFF8 (HISTORY_LOG_UUID) notifications.
     *
     * After an opcode 60 request is sent on FFF6, the pump sends history
     * log records as packetized messages on FFF8. Uses the same PacketAssembler
     * + Packetize.parseHeader flow as status responses, completing the
     * [historyLogDeferred] when a full message arrives.
     */
    private fun handleHistoryLogNotification(data: ByteArray) {
        Timber.d("BLE_RAW RX_HIST len=%d hex=%s", data.size, data.toSpacedHex())

        val deferred = historyLogDeferred ?: return

        val raw: ByteArray
        synchronized(historyLogAssembler) {
            if (!historyLogAssembler.feed(data)) return
            raw = historyLogAssembler.assemble()
            historyLogAssembler.reset()
        }

        // Extract cargo from this packet
        val cargo = Packetize.parseHeader(raw)?.let { (opcode, _, c) ->
            Timber.d("BLE_RAW RX_HIST_PARSED opcode=0x%02x cargoLen=%d", opcode, c.size)
            c
        } ?: raw.also {
            Timber.d("BLE_RAW RX_HIST_RAW len=%d", raw.size)
        }

        // Accumulate cargo into buffer and (re)start idle timeout.
        // The pump sends multiple independent FFF8 packets per opcode 60 request.
        // After 500ms of no new packets, we deliver all collected cargos.
        // All buffer/job access is synchronized to prevent races between
        // near-simultaneous GATT callback invocations.
        synchronized(historyLogAssembler) {
            historyLogBuffer.add(cargo)
            historyLogIdleJob?.cancel()
            historyLogIdleJob = scope.launch {
                delay(HISTORY_LOG_IDLE_TIMEOUT_MS)
                val packets: List<ByteArray>
                synchronized(historyLogAssembler) {
                    packets = historyLogBuffer.toList()
                    Timber.d("BLE_RAW RX_HIST_COMPLETE packets=%d totalBytes=%d",
                        packets.size, packets.sumOf { it.size })
                    historyLogBuffer.clear()
                }
                // Re-read deferred to avoid completing a stale reference
                // if the request timed out and was discarded.
                historyLogDeferred?.complete(packets)
            }
        }
    }

    private fun startAuthentication() {
        // The pump requires app-level auth (JPAKE) on EVERY connection,
        // including reconnects. Without it, the pump silently ignores all
        // status requests even with a valid BLE bond.
        //
        // JPAKE has two modes:
        // - BOOTSTRAP: Full 5-round-trip handshake. Requires pump in pairing mode.
        // - CONFIRMATION: 2-round-trip handshake using saved derived secret.
        //   Works on reconnect without pairing mode.
        val isReconnect = pendingPairingCode == null && credentialStore.isPaired()
        val code = pendingPairingCode ?: credentialStore.getPairingCode()
        if (code == null) {
            Timber.e("No pairing code available for authentication")
            _connectionState.value = ConnectionState.AUTH_FAILED
            return
        }

        // Start handshake timeout -- fail if auth doesn't complete in time
        authTimeoutJob?.cancel()
        authTimeoutJob = scope.launch {
            delay(AUTH_TIMEOUT_MS)
            if (_connectionState.value == ConnectionState.AUTHENTICATING) {
                Timber.e("Authentication handshake timed out after %d ms", AUTH_TIMEOUT_MS)
                _connectionState.value = ConnectionState.AUTH_FAILED
            }
        }

        // Use JPAKE for 6-digit codes (firmware v7.7+), V1 for 16-char codes.
        if (code.length <= 10) {
            jpakeAuthenticator.reset()
            val savedSecretHex = credentialStore.getJpakeDerivedSecret()
            if (isReconnect && savedSecretHex != null) {
                // CONFIRMATION mode: skip rounds 1-2, jump to round 3 using
                // the derived secret saved from the initial bootstrap pairing.
                Timber.d("Starting JPAKE CONFIRMATION mode (reconnect, saved secret available)")
                val secretBytes = hexStringToByteArray(savedSecretHex)
                val chunks = jpakeAuthenticator.buildJpake3RequestFromDerivedSecret(
                    secretBytes, nextTxId(),
                )
                enqueueWrite(TandemProtocol.AUTHORIZATION_UUID, chunks)
            } else {
                // BOOTSTRAP mode: full 5-round-trip handshake.
                // Pump must be in pairing mode (code from pump screen or body).
                Timber.d("Starting JPAKE BOOTSTRAP mode (initial pair, code length=%d)", code.length)
                val chunks = jpakeAuthenticator.buildJpake1aRequest(code, nextTxId())
                enqueueWrite(TandemProtocol.AUTHORIZATION_UUID, chunks)
            }
        } else {
            Timber.d("Starting V1 authentication (code length=%d)", code.length)
            authenticator.reset()
            val chunks = authenticator.buildCentralChallengeRequest(nextTxId())
            enqueueWrite(TandemProtocol.AUTHORIZATION_UUID, chunks)
        }
    }

    /** Convert a hex string (no separators) to a ByteArray. */
    private fun hexStringToByteArray(hex: String): ByteArray {
        val clean = hex.replace(" ", "")
        return ByteArray(clean.length / 2) { i ->
            clean.substring(i * 2, i * 2 + 2).toInt(16).toByte()
        }
    }

    private fun onAuthSuccess() {
        authTimeoutJob?.cancel()
        authTimeoutJob = null
        reconnectAttempt = 0
        rapidDisconnectCount = 0
        encryptionFailureCount = 0
        consecutiveReconnectFailures = 0
        synchronized(autoConnectLock) {
            reconnectPhase = ReconnectPhase.FAST
        }
        cancelAutoConnectGatt()
        hadSuccessfulSession = true
        // Save credentials on first successful pairing
        val address = synchronized(gattLock) { gatt?.device?.address }
        val code = pendingPairingCode
        if (address != null && code != null) {
            credentialStore.savePairing(address, code)
            pendingPairingCode = null
        }
        // Save JPAKE derived credentials for confirmation mode reconnect.
        // After initial bootstrap, the derived secret allows reconnection
        // without the pump being in pairing mode.
        val secret = jpakeAuthenticator.getDerivedSecret()
        val nonce = jpakeAuthenticator.getServerNonce()
        if (secret != null && nonce != null) {
            credentialStore.saveJpakeCredentials(
                derivedSecretHex = secret.joinToString("") { "%02x".format(it.toInt() and 0xFF) },
                serverNonceHex = nonce.joinToString("") { "%02x".format(it.toInt() and 0xFF) },
            )
            Timber.d("JPAKE credentials saved for confirmation mode reconnect")
        }
        // Send initialization sequence (API version, pump version, time since reset)
        // before allowing status reads. pumpX2 sends these after auth to fully
        // establish the session -- without them the pump may drop the connection
        // after a few status responses.
        Timber.d("Pump authenticated, sending initialization sequence")
        sendInitSequence()

        // Post-auth settle: give the pump time to process the init messages
        // before we flood it with status requests.
        Timber.d("Settling for %d ms before allowing reads", POST_AUTH_SETTLE_MS)
        settleJob?.cancel()
        settleJob = scope.launch {
            delay(POST_AUTH_SETTLE_MS)
            // Guard: only transition if we haven't been disconnected during the delay
            if (_connectionState.value == ConnectionState.AUTHENTICATING) {
                _connectionState.value = ConnectionState.CONNECTED
                Timber.d("Pump connected and ready for status requests")
            }
        }
    }

    /**
     * Send post-auth initialization requests that pumpX2 sends to establish
     * the session. These are fire-and-forget -- we don't need the responses,
     * but the pump needs to see them before accepting status reads.
     */
    private fun sendInitSequence() {
        val initOpcodes = intArrayOf(
            TandemProtocol.OPCODE_API_VERSION_REQ,
            TandemProtocol.OPCODE_PUMP_VERSION_REQ,
            TandemProtocol.OPCODE_TIME_SINCE_RESET_REQ,
        )
        for (opcode in initOpcodes) {
            val id = nextTxId()
            Timber.d("Init TX opcode=0x%02x (%s) txId=%d",
                opcode, TandemProtocol.opcodeName(opcode), id)
            val chunks = Packetize.encode(opcode, id, ByteArray(0), TandemProtocol.CHUNK_SIZE_SHORT)
            enqueueWrite(TandemProtocol.CURRENT_STATUS_UUID, chunks)
        }
    }

    private fun handleAuthNotification(data: ByteArray) {
        val assembler = assemblers.getOrPut(TandemProtocol.AUTHORIZATION_UUID) { PacketAssembler() }
        val raw: ByteArray
        synchronized(assembler) {
            if (!assembler.feed(data)) return
            raw = assembler.assemble()
            assembler.reset()
        }

        val parsed = Packetize.parseHeader(raw) ?: run {
            Timber.e("Failed to parse auth notification len=%d", raw.size)
            debugLogger.logPacket(
                direction = DebugLogger.Direction.RX,
                opcode = if (raw.isNotEmpty()) raw[0].toInt() and 0xFF else -1,
                opcodeName = "AUTH_PARSE_FAIL",
                txId = -1,
                cargoHex = raw.toSpacedHex(),
                cargoSize = raw.size,
                error = "Auth CRC or header parse failed",
            )
            return
        }

        val (opcode, authTxId, cargo) = parsed
        Timber.d("BLE_RAW AUTH opcode=0x%02x txId=%d cargoLen=%d",
            opcode, authTxId, cargo.size)
        debugLogger.logPacket(
            direction = DebugLogger.Direction.RX,
            opcode = opcode,
            opcodeName = TandemProtocol.opcodeName(opcode),
            txId = authTxId,
            cargoHex = cargo.toSpacedHex(),
            cargoSize = cargo.size,
        )

        when (opcode) {
            // -- V1 authentication opcodes --
            TandemProtocol.OPCODE_CENTRAL_CHALLENGE_RESP -> {
                val code = pendingPairingCode ?: credentialStore.getPairingCode() ?: run {
                    Timber.e("No pairing code available for challenge response")
                    _connectionState.value = ConnectionState.AUTH_FAILED
                    return
                }
                val chunks = authenticator.processChallengeResponse(cargo, code, nextTxId())
                if (chunks != null) {
                    enqueueWrite(TandemProtocol.AUTHORIZATION_UUID, chunks)
                } else {
                    Timber.e("Auth: failed to build PumpChallengeRequest (bad state or response)")
                    _connectionState.value = ConnectionState.AUTH_FAILED
                }
            }
            TandemProtocol.OPCODE_PUMP_CHALLENGE_RESP -> {
                val success = authenticator.processPumpChallengeResponse(cargo)
                if (success) {
                    onAuthSuccess()
                } else {
                    Timber.e("Pump authentication rejected by pump")
                    _connectionState.value = ConnectionState.AUTH_FAILED
                }
            }

            // -- JPAKE authentication opcodes --
            TandemProtocol.OPCODE_JPAKE_1A_RESP -> {
                if (!jpakeAuthenticator.processJpake1aResponse(cargo)) {
                    _connectionState.value = ConnectionState.AUTH_FAILED
                    return
                }
                val chunks = jpakeAuthenticator.buildJpake1bRequest(nextTxId())
                enqueueWrite(TandemProtocol.AUTHORIZATION_UUID, chunks)
            }
            TandemProtocol.OPCODE_JPAKE_1B_RESP -> {
                if (!jpakeAuthenticator.processJpake1bResponse(cargo)) {
                    _connectionState.value = ConnectionState.AUTH_FAILED
                    return
                }
                val chunks = jpakeAuthenticator.buildJpake2Request(nextTxId())
                if (chunks.isEmpty()) {
                    _connectionState.value = ConnectionState.AUTH_FAILED
                    return
                }
                enqueueWrite(TandemProtocol.AUTHORIZATION_UUID, chunks)
            }
            TandemProtocol.OPCODE_JPAKE_2_RESP -> {
                if (!jpakeAuthenticator.processJpake2Response(cargo)) {
                    _connectionState.value = ConnectionState.AUTH_FAILED
                    return
                }
                val chunks = jpakeAuthenticator.buildJpake3Request(nextTxId())
                if (chunks.isEmpty()) {
                    _connectionState.value = ConnectionState.AUTH_FAILED
                    return
                }
                enqueueWrite(TandemProtocol.AUTHORIZATION_UUID, chunks)
            }
            TandemProtocol.OPCODE_JPAKE_3_SESSION_KEY_RESP -> {
                if (!jpakeAuthenticator.processJpake3Response(cargo)) {
                    // If confirmation mode was rejected, the derived secret may
                    // be stale (e.g., pump was factory reset). Clear saved
                    // credentials so the next attempt uses bootstrap mode.
                    Timber.w("JPAKE round 3 failed, clearing saved JPAKE credentials")
                    credentialStore.clearJpakeCredentials()
                    _connectionState.value = ConnectionState.AUTH_FAILED
                    return
                }
                val chunks = jpakeAuthenticator.buildJpake4Request(nextTxId())
                enqueueWrite(TandemProtocol.AUTHORIZATION_UUID, chunks)
            }
            TandemProtocol.OPCODE_JPAKE_4_KEY_CONFIRM_RESP -> {
                val success = jpakeAuthenticator.processJpake4Response(cargo)
                if (success) {
                    onAuthSuccess()
                } else {
                    Timber.e("JPAKE: Key confirmation failed, clearing saved JPAKE credentials")
                    credentialStore.clearJpakeCredentials()
                    _connectionState.value = ConnectionState.AUTH_FAILED
                }
            }

            else -> {
                Timber.w("Auth: unexpected opcode %d in auth notification", opcode)
            }
        }
    }

    companion object {
        /** Idle timeout (ms) after the last FFF8 notification before completing the stream. */
        private const val HISTORY_LOG_IDLE_TIMEOUT_MS = 500L

        /** Post-auth settle delay (ms) before setting CONNECTED state.
         *  After JPAKE completes and init sequence is sent, this gives the pump
         *  time to process initialization before we send status requests.
         *  Keep short to avoid idle-timeout disconnects from the pump.
         */
        private const val POST_AUTH_SETTLE_MS = 500L

        /** Auth handshake timeout. JPAKE has 5 round trips; 30s is generous. */
        private const val AUTH_TIMEOUT_MS = 30_000L

        /** Max consecutive rapid disconnections before declaring bond lost. */
        private const val MAX_RAPID_DISCONNECTS = 3

        /** Max connections with zero pump responses before giving up. */
        private const val MAX_ZERO_RESPONSE_CONNECTIONS = 3

        /** Max consecutive INSUFFICIENT_ENCRYPTION disconnects (during active sessions
         *  or reconnection after a prior successful session) before treating the bond
         *  as genuinely stale and removing it. */
        private const val MAX_ENCRYPTION_FAILURES = 3

        /** Max attempts in the fast reconnection phase before transitioning to
         *  slow (patient) reconnection. With 32s max backoff, 10 attempts takes
         *  ~5 minutes. After this, reconnection continues indefinitely at a
         *  slower rate (every 2 minutes) with autoConnect=true as a supplement. */
        private const val MAX_FAST_RECONNECT_ATTEMPTS = 10

        /** Interval for slow-phase periodic reconnection attempts (2 minutes).
         *  Runs alongside a passive autoConnect=true GATT. The periodic timer
         *  is a fallback for devices with buggy autoConnect implementations. */
        private const val SLOW_RECONNECT_INTERVAL_MS = 120_000L

        /** Cap for [consecutiveReconnectFailures] to prevent unbounded growth.
         *  Only used for logging; the slow phase reconnects indefinitely. */
        private const val MAX_CONSECUTIVE_RECONNECT_FAILURES = 100

        // Named GATT status codes used in bond-loss detection
        private const val GATT_INSUFFICIENT_AUTHENTICATION = 0x05
        private const val GATT_INSUFFICIENT_ENCRYPTION = 0x08
        private const val GATT_CONN_TERMINATE_PEER_USER = 0x13

        /** Convert a GATT status code to a human-readable name. */
        fun gattStatusName(status: Int): String = when (status) {
            0 -> "SUCCESS"
            2 -> "READ_NOT_PERMITTED"
            5 -> "INSUFFICIENT_AUTHENTICATION"
            6 -> "REQUEST_NOT_SUPPORTED"
            7 -> "INVALID_OFFSET"
            8 -> "INSUFFICIENT_ENCRYPTION"
            0x0D -> "INVALID_ATTRIBUTE_LENGTH"
            0x13 -> "CONN_TERMINATE_PEER_USER"
            0x16 -> "CONN_TERMINATE_LOCAL_HOST"
            0x22 -> "CONN_FAILED_ESTABLISHMENT"
            0x3B -> "UNSPECIFIED_ERROR"
            0x3E -> "CONN_TIMEOUT"
            0x85 -> "GATT_ERROR"
            0x101 -> "GATT_FAILURE"
            else -> "UNKNOWN_0x${status.toString(16)}"
        }
    }
}

/** Reconnection phase: fast exponential backoff, then slow periodic. */
private enum class ReconnectPhase {
    /** Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s. ~5 minutes total. */
    FAST,
    /** Periodic every 2 minutes with autoConnect=true supplement. Runs indefinitely. */
    SLOW,
}
