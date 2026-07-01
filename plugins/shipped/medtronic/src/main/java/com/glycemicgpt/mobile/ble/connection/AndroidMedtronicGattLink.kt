/*
 * On-device BluetoothGatt-CLIENT transport for the Medtronic MiniMed 700-series read-only driver.
 *
 * GlycemicGPT code (GPL-3.0). The concrete Android implementation of the [MedtronicGattLink] seam
 * (Milestone D). In the inverted topology the pump connects to the phone (peripheral) for advertising
 * + SAKE, but to read the pump's data the phone opens a GATT *client* connection back to the *pump's*
 * GATT server over that same link -- exactly as OpenMinimed's PythonPumpConnector does over BlueZ
 * (GPL-3.0, used with permission): write the control point, subscribe for notifications, read static
 * characteristics. The connected pump [BluetoothDevice] is obtained from
 * [MedtronicBleConnectionManager.connectedPumpDevice] (captured when the pump connected to our GATT
 * server); this never starts a fresh scan/advertise cycle for it.
 *
 * READ-ONLY: only static reads and report/control-point writes (RACP / CGM SOCP / IDD SRCP, plus the
 * CCCD descriptor) are issued; [write] refuses any characteristic outside that allow-list, so no
 * therapeutic write opcode can be sent. MTU stays at 23 -- we never call `requestMtu()`; outbound
 * payloads arrive pre-fragmented to <= 20-byte PDUs via
 * [com.glycemicgpt.mobile.ble.protocol.PduFramer] and inbound reassembly stays above the seam.
 *
 * Over-the-air validation against a real pump rides with 48.A2 / Milestone F -- in particular that a
 * second (client) GATT connection attaches to the existing link rather than opening a new one. Nothing
 * here is claimed live-verified.
 */
package com.glycemicgpt.mobile.ble.connection

import android.annotation.SuppressLint
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothProfile
import android.bluetooth.BluetoothStatusCodes
import android.content.Context
import android.os.Build
import com.glycemicgpt.mobile.ble.protocol.MedtronicProtocol
import com.glycemicgpt.mobile.ble.read.MedtronicGattLink
import com.glycemicgpt.mobile.ble.read.MedtronicReadException
import com.glycemicgpt.mobile.ble.read.MedtronicCodec
import com.glycemicgpt.mobile.ble.read.MedtronicReadGateway
import timber.log.Timber
import java.util.UUID
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/**
 * `BluetoothGatt`-client implementation of [MedtronicGattLink].
 *
 * **Blocking + serialized.** Android allows one outstanding GATT operation at a time, so every
 * [read]/[write]/[subscribe]/[unsubscribe] -- and the watchdog cleanup -- runs under [opLock] and
 * blocks the calling thread (the gateway's IO dispatcher) until the matching GATT callback fires,
 * bounded by [operationTimeoutMs]. The connection is opened lazily on first use and reused until the
 * pump disconnects. The link assumes **one exchange at a time**: the read gateway issues a single
 * read per call and polling orchestration (Milestone D2) serializes across readers; concurrent
 * exchanges over one BLE link are not a real pump scenario and are not supported here.
 *
 * **Stale-completion safety.** GATT callbacks for an operation can arrive after that operation's
 * timeout. A request timeout therefore tears the client GATT down ([closeGatt]); the operational
 * callbacks below reject any callback whose `BluetoothGatt` is not the current one ([gatt]), so a late
 * completion from a timed-out op lands on a now-discarded handle and can never satisfy a later op's
 * slot.
 *
 * **Threading contract (AC3).** Inbound notification PDUs are hopped onto [worker] -- the connection
 * manager's existing single SAKE worker thread -- so every `onPdu` callback is delivered serialized on
 * one thread, as [com.glycemicgpt.mobile.ble.read.MedtronicSessionReader] requires. No second thread
 * is spun up for delivery.
 *
 * **RACP service-scoping (AC2).** The shared SIG `0x2A52` RACP characteristic lives under both the CGM
 * and IDD services. It is resolved to the most recently resolved RACP-bearing service -- the reader
 * resolves that exchange's data characteristic (CGM Measurement / IDD History Data) immediately before
 * touching the control point, so this tracks the current exchange -- falling back to a service with a
 * live subscription only if that context is somehow unset. Preferring the resolved context over live
 * subscriptions keeps a dangling handler from a failed prior exchange from hijacking the scope; it is
 * never the bare UUID, and never poisoned by an unrelated Battery/Device-Info read.
 *
 * **Cancellation/cleanup (AC4).** A reader only [unsubscribe]s on a pump *response*; if the gateway's
 * per-operation timeout cancels the driving coroutine first, the subscriptions would dangle. A
 * [watchdog] armed while subscriptions are open releases them (drops handlers + disables CCCD) once
 * the exchange can no longer succeed, so a timed-out read leaves no notifications that desync the next
 * one.
 *
 * @param deviceProvider supplies the connected pump device, or `null` when no pump is connected.
 * @param worker the connection manager's serial worker; inbound PDUs are delivered on it.
 */
@SuppressLint("MissingPermission")
class AndroidMedtronicGattLink(
    context: Context,
    private val deviceProvider: () -> BluetoothDevice?,
    private val worker: SerialWorker,
    private val watchdog: SubscriptionWatchdog = ScheduledSubscriptionWatchdog(),
    private val operationTimeoutMs: Long = DEFAULT_OPERATION_TIMEOUT_MS,
    private val connectTimeoutMs: Long = DEFAULT_CONNECT_TIMEOUT_MS,
    private val subscriptionTimeoutMs: Long = MedtronicReadGateway.DEFAULT_OPERATION_TIMEOUT_MS,
) : MedtronicGattLink {

    private val appContext = context.applicationContext

    // Only one GATT operation may be in flight at a time; every operation serializes here.
    private val opLock = ReentrantLock()

    @Volatile
    private var gatt: BluetoothGatt? = null

    @Volatile
    private var connectedAddress: String? = null

    @Volatile
    private var servicesReady = false

    // Built once per connection from the discovered GATT table: bare characteristic UUID -> the
    // (service, characteristic) pairs exposing it. The RACP UUID maps to more than one entry.
    @Volatile
    private var serviceIndex: Map<UUID, List<ResolvedChar>> = emptyMap()

    // The services that expose the shared RACP characteristic (CGM + IDD). Only reads of characteristics
    // in these services update [lastResolvedServiceUuid], so an unrelated Battery/Device-Info read can
    // never poison RACP scoping.
    @Volatile
    private var racpServiceUuids: Set<UUID> = emptySet()

    // The service of the most recently resolved RACP-bearing characteristic -- the primary context for
    // scoping the shared RACP UUID. An active data subscription resolves this immediately before the
    // RACP write, so it tracks the current exchange rather than any stale handler still in the map.
    @Volatile
    private var lastResolvedServiceUuid: UUID? = null

    // The completion slot for the in-flight read/write/descriptor operation (set under [opLock]); the
    // GATT callback offers the outcome here. A separate slot is used for connect/discover.
    @Volatile
    private var pending: ArrayBlockingQueue<GattOutcome>? = null

    @Volatile
    private var connectPending: ArrayBlockingQueue<GattOutcome>? = null

    // The BluetoothGatt of the in-flight connect attempt. Connect-phase callbacks are accepted only for
    // this handle, so a late callback from a prior (timed-out) attempt can't complete a newer one. Null
    // while no connect is in progress -- a callback arriving then is tolerated (the matching
    // [connectPending] is also null, so the offer is a no-op).
    @Volatile
    private var connectingGatt: BluetoothGatt? = null

    @Volatile
    private var watchdogHandle: SubscriptionWatchdog.Handle? = null

    // Active notification subscriptions keyed by the bare characteristic UUID the caller subscribed.
    // Concurrent so the binder-thread teardown and the worker-thread delivery can read it safely.
    private val handlers = ConcurrentHashMap<UUID, ActiveSubscription>()

    // -- MedtronicGattLink ---------------------------------------------------

    override fun read(characteristic: UUID): ByteArray =
        opLock.withLock {
            val link = ensureConnected()
            val resolved = resolve(characteristic)
            val outcome = awaitGatt("read", characteristic) { link.readCharacteristic(resolved.characteristic) }
            if (outcome.status != BluetoothGatt.GATT_SUCCESS) {
                logGattWarning("read", characteristic, outcome.status)
                throw MedtronicReadException("Medtronic GATT read failed (status=${outcome.status})")
            }
            val result = outcome.value ?: ByteArray(0)
            Timber.v("GATT read %s (%d bytes) %s", characteristic, result.size, MedtronicCodec.toHex(result))
            result
        }

    override fun write(characteristic: UUID, value: ByteArray) {
        if (characteristic !in WRITABLE_CONTROL_POINTS) {
            // READ-ONLY defense-in-depth: only the report/control points are ever written, so a buggy
            // caller can never issue a therapeutic write. Keep the UUID at DEBUG (not Sentry-eligible).
            Timber.w("Medtronic GATT write refused: characteristic is not a permitted control point")
            Timber.d("Medtronic GATT write refused for %s", characteristic)
            return
        }
        // Best-effort: a failed control-point write degrades to the gateway's operation timeout (the
        // pump simply never responds) rather than escaping the readers' Result<T> contract.
        try {
            opLock.withLock {
                val link = ensureConnected()
                val resolved = resolve(characteristic)
                Timber.v("GATT write %s (%d bytes) %s", characteristic, value.size, MedtronicCodec.toHex(value))
                val outcome = awaitGatt("write", characteristic) { writeCharacteristic(link, resolved.characteristic, value) }
                if (outcome.status != BluetoothGatt.GATT_SUCCESS) {
                    logGattWarning("write", characteristic, outcome.status)
                    handlers.remove(characteristic)
                }
            }
        } catch (e: MedtronicReadException) {
            logOperationFailure("write", characteristic, e)
        }
    }

    override fun subscribe(characteristic: UUID, onPdu: (ByteArray) -> Unit) {
        try {
            opLock.withLock {
                val link = ensureConnected()
                val resolved = resolve(characteristic)
                val char = resolved.characteristic
                val cccd = char.getDescriptor(MedtronicProtocol.CCCD_UUID)
                if (cccd == null) {
                    Timber.w("Medtronic GATT subscribe: no CCCD on the target characteristic")
                    return
                }
                if (!link.setCharacteristicNotification(char, true)) {
                    // Android won't route notifications to our callback, so enabling the CCCD would only
                    // make the reader wait out its timeout for data it can never receive. Abort now.
                    Timber.w("Medtronic GATT subscribe: setCharacteristicNotification was rejected")
                    return
                }
                // Register the handler before enabling notifications so a PDU delivered the instant the
                // CCCD takes effect is not lost. Re-subscribing replaces the handler (seam contract).
                // Record the owning client so a deferred unsubscribe can't disable a later connection.
                handlers[characteristic] = ActiveSubscription(resolved, onPdu, link)
                val isIndication = isIndication(char)
                val enable = if (isIndication) CCCD_ENABLE_INDICATION else CCCD_ENABLE_NOTIFICATION
                Timber.v("GATT subscribe %s (%s)", characteristic, if (isIndication) "indication" else "notification")
                // The CCCD write completes before this returns, so notifications are effective before
                // the caller's subsequent control-point write (AC3).
                val outcome = awaitGatt("subscribe", characteristic) { writeDescriptor(link, cccd, enable) }
                if (outcome.status != BluetoothGatt.GATT_SUCCESS) {
                    logGattWarning("subscribe", characteristic, outcome.status)
                    // The CCCD never took effect; drop the handler so it isn't a phantom subscription.
                    handlers.remove(characteristic)
                    return
                }
                armWatchdog()
            }
        } catch (e: MedtronicReadException) {
            // On a timeout [awaitGatt] already tore the connection down, clearing handlers; nothing to undo.
            logOperationFailure("subscribe", characteristic, e)
        }
    }

    override fun unsubscribe(characteristic: UUID) {
        // Drop the handler first, lock-free: this is the AC4 correctness guarantee (no notification
        // reaches a finished exchange). A reader calls unsubscribe from inside its onPdu handler, which
        // runs on the shared worker thread, so the blocking CCCD-disable round trip is run off that
        // thread (the cleanup executor) -- otherwise it would stall connection-lifecycle events.
        val sub = handlers.remove(characteristic) ?: return
        if (handlers.isEmpty()) cancelWatchdog()
        watchdog.execute { disableNotifications("unsubscribe", sub) }
    }

    // -- Connection / discovery ---------------------------------------------

    private fun ensureConnected(): BluetoothGatt {
        val device = deviceProvider()
            ?: throw MedtronicReadException("Medtronic GATT read skipped: pump not connected")
        val existing = gatt
        if (existing != null && servicesReady && connectedAddress == device.address) return existing

        closeGatt()
        val slot = ArrayBlockingQueue<GattOutcome>(1)
        connectPending = slot
        val opened =
            try {
                device.connectGatt(appContext, false, gattCallback, BluetoothDevice.TRANSPORT_LE)
            } catch (e: SecurityException) {
                connectPending = null
                throw MedtronicReadException("Medtronic GATT connect failed: ${e.javaClass.simpleName}", e)
            }
        if (opened == null) {
            connectPending = null
            throw MedtronicReadException("Medtronic GATT connect returned no client")
        }
        connectingGatt = opened
        val outcome = slot.poll(connectTimeoutMs, TimeUnit.MILLISECONDS)
        connectPending = null
        connectingGatt = null
        if (outcome == null || outcome.status != BluetoothGatt.GATT_SUCCESS) {
            logGattWarning("connect", null, outcome?.status ?: SYNTHETIC_TIMEOUT_STATUS)
            closeClient(opened)
            throw MedtronicReadException("Medtronic GATT connect/discover failed (status=${outcome?.status ?: "timeout"})")
        }
        // Publish the handle only after connect + discovery succeeded, so a racing disconnect callback
        // can't null a half-initialized connection out from under the next operation.
        gatt = opened
        connectedAddress = device.address
        buildServiceIndex(opened)
        servicesReady = true
        return opened
    }

    private fun buildServiceIndex(link: BluetoothGatt) {
        val index = HashMap<UUID, MutableList<ResolvedChar>>()
        for (service in link.services) {
            for (char in service.characteristics) {
                index.getOrPut(char.uuid) { mutableListOf() }.add(ResolvedChar(service.uuid, char))
            }
        }
        serviceIndex = index
        racpServiceUuids = index[MedtronicProtocol.RACP_UUID].orEmpty().mapTo(HashSet()) { it.serviceUuid }
    }

    private fun closeGatt() {
        cancelWatchdog()
        handlers.clear()
        serviceIndex = emptyMap()
        racpServiceUuids = emptySet()
        lastResolvedServiceUuid = null
        servicesReady = false
        gatt?.let { closeClient(it) }
        gatt = null
        connectedAddress = null
    }

    private fun closeClient(link: BluetoothGatt) {
        try {
            link.disconnect()
            link.close()
        } catch (e: SecurityException) {
            Timber.w("Medtronic GATT close failed: %s", e.javaClass.simpleName)
        }
    }

    // -- Characteristic resolution (AC2) ------------------------------------

    private fun resolve(characteristic: UUID): ResolvedChar {
        val candidates = serviceIndex[characteristic].orEmpty()
        return when {
            candidates.isEmpty() ->
                throw MedtronicReadException("Medtronic GATT characteristic not found in the pump's services")
            candidates.size == 1 -> candidates[0].also { rememberServiceContext(it.serviceUuid) }
            else -> resolveAmbiguous(candidates)
        }
    }

    /**
     * Record the service context used to scope the shared RACP characteristic, but only for services
     * that actually expose RACP (CGM + IDD). A Battery / Device-Info read must not move the CGM-vs-IDD
     * scoping context.
     */
    private fun rememberServiceContext(serviceUuid: UUID) {
        if (serviceUuid in racpServiceUuids) lastResolvedServiceUuid = serviceUuid
    }

    /**
     * Scope a characteristic exposed by more than one service (the shared `0x2A52` RACP). Bind it to the
     * most recently resolved RACP-bearing service ([lastResolvedServiceUuid]) -- the reader resolves this
     * exchange's data char (CGM Measurement / IDD History Data) immediately before the RACP write, so it
     * is the current exchange's service -- and fall back to a service with a live subscription only if
     * that context is unset. Checking the resolved context before active subscriptions keeps a dangling
     * handler from a failed prior exchange from hijacking the scope. Guessing here silently reads the
     * wrong log, so an unresolvable case fails loudly rather than picking the first candidate.
     */
    private fun resolveAmbiguous(candidates: List<ResolvedChar>): ResolvedChar {
        val activeServices = handlers.values.mapTo(HashSet()) { it.resolved.serviceUuid }
        return candidates.firstOrNull { it.serviceUuid == lastResolvedServiceUuid }
            ?: candidates.firstOrNull { it.serviceUuid in activeServices }
            ?: throw MedtronicReadException("Medtronic GATT could not scope a shared characteristic to a service")
    }

    // -- Operation plumbing -------------------------------------------------

    private fun awaitGatt(
        op: String,
        characteristic: UUID?,
        tearDownOnTimeout: Boolean = true,
        issue: () -> Boolean,
    ): GattOutcome {
        val slot = ArrayBlockingQueue<GattOutcome>(1)
        pending = slot
        val started =
            try {
                issue()
            } catch (e: SecurityException) {
                pending = null
                throw MedtronicReadException("Medtronic GATT $op failed: ${e.javaClass.simpleName}", e)
            }
        if (!started) {
            pending = null
            throw MedtronicReadException("Medtronic GATT $op was rejected by the stack")
        }
        val outcome = slot.poll(operationTimeoutMs, TimeUnit.MILLISECONDS)
        pending = null
        return outcome ?: run {
            logGattWarning(op, characteristic, SYNTHETIC_TIMEOUT_STATUS)
            // Discard the desynchronized connection so the timed-out op's late callback lands on a
            // stale handle (rejected by the identity guard) instead of a later op's slot.
            if (tearDownOnTimeout) closeGatt()
            throw MedtronicReadException("Medtronic GATT $op timed out after $operationTimeoutMs ms")
        }
    }

    private fun writeCharacteristic(link: BluetoothGatt, char: BluetoothGattCharacteristic, value: ByteArray): Boolean =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            link.writeCharacteristic(char, value, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) ==
                BluetoothStatusCodes.SUCCESS
        } else {
            @Suppress("DEPRECATION")
            char.value = value
            @Suppress("DEPRECATION")
            char.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
            @Suppress("DEPRECATION")
            link.writeCharacteristic(char)
        }

    private fun writeDescriptor(link: BluetoothGatt, descriptor: BluetoothGattDescriptor, value: ByteArray): Boolean =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            link.writeDescriptor(descriptor, value) == BluetoothStatusCodes.SUCCESS
        } else {
            @Suppress("DEPRECATION")
            descriptor.value = value
            @Suppress("DEPRECATION")
            link.writeDescriptor(descriptor)
        }

    private fun isIndication(char: BluetoothGattCharacteristic): Boolean =
        (char.properties and BluetoothGattCharacteristic.PROPERTY_INDICATE) != 0

    /** Disable notifications for [sub], serialized under [opLock] so its CCCD write owns its own slot. */
    private fun disableNotifications(op: String, sub: ActiveSubscription) {
        try {
            opLock.withLock {
                val link = gatt ?: return
                // This cleanup may be deferred (run off the worker / on the watchdog) and the client may
                // have been replaced by a reconnect meanwhile. The old connection's subscriptions died
                // with it, so skip rather than disable a characteristic on the new connection.
                if (link !== sub.ownerGatt) return
                val char = sub.resolved.characteristic
                if (!link.setCharacteristicNotification(char, false)) {
                    Timber.w("Medtronic GATT %s: setCharacteristicNotification(false) was rejected", op)
                }
                val cccd = char.getDescriptor(MedtronicProtocol.CCCD_UUID) ?: return
                // Best-effort: don't tear the connection down if the disable is lost.
                val outcome = awaitGatt(op, char.uuid, tearDownOnTimeout = false) { writeDescriptor(link, cccd, CCCD_DISABLE) }
                if (outcome.status != BluetoothGatt.GATT_SUCCESS) {
                    logGattWarning(op, char.uuid, outcome.status)
                }
            }
        } catch (e: MedtronicReadException) {
            logOperationFailure(op, sub.resolved.characteristic.uuid, e)
        }
    }

    // -- Watchdog (AC4) -----------------------------------------------------

    private fun armWatchdog() {
        watchdogHandle?.cancel()
        watchdogHandle = watchdog.schedule(subscriptionTimeoutMs) { onWatchdogFire() }
    }

    private fun cancelWatchdog() {
        watchdogHandle?.cancel()
        watchdogHandle = null
    }

    private fun onWatchdogFire() {
        if (handlers.isEmpty()) return
        // The driving read's coroutine has been cancelled by the gateway's operation timeout without the
        // reader unsubscribing (it only unsubscribes on a pump response). Release every dangling
        // subscription so the timed-out read leaves no notifications that desync the next exchange.
        Timber.w("Medtronic GATT subscription watchdog fired; releasing dangling subscriptions")
        cancelWatchdog()
        // Drop handlers first (lock-free): the no-dangling-notification guarantee. The CCCD disables
        // then run serialized under [opLock] so each owns its own completion slot.
        val orphaned = handlers.values.toList()
        handlers.clear()
        for (sub in orphaned) disableNotifications("watchdog-release", sub)
    }

    // -- GATT callback (binder thread) --------------------------------------

    // A connect-phase callback (CONNECTED / services-discovered / a disconnect of the connecting handle)
    // is stale if it belongs to a BluetoothGatt other than the one the current attempt opened. While no
    // connect is in progress [connectingGatt] is null and the callback is tolerated (connectPending is
    // also null then, so any offer is a no-op).
    private fun isStaleConnectCallback(g: BluetoothGatt): Boolean =
        connectingGatt != null && g !== connectingGatt

    private val gattCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            when (newState) {
                BluetoothProfile.STATE_CONNECTED -> {
                    if (isStaleConnectCallback(g)) return
                    if (status != BluetoothGatt.GATT_SUCCESS) {
                        connectPending?.offer(GattOutcome(status, null))
                        return
                    }
                    // Never requestMtu(): the pump only honors 23-byte PDUs (AC5). Go straight to
                    // discovery.
                    val started =
                        try {
                            g.discoverServices()
                        } catch (e: SecurityException) {
                            Timber.w("Medtronic GATT discoverServices failed: %s", e.javaClass.simpleName)
                            false
                        }
                    if (!started) connectPending?.offer(GattOutcome(SYNTHETIC_REJECTED_STATUS, null))
                }
                BluetoothProfile.STATE_DISCONNECTED -> teardownOnDisconnect(g, status)
            }
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            if (isStaleConnectCallback(g)) return
            connectPending?.offer(GattOutcome(status, null))
        }

        override fun onCharacteristicRead(
            g: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray,
            status: Int,
        ) {
            if (g !== gatt) return
            pending?.offer(GattOutcome(status, value.copyOf()))
        }

        @Deprecated("Deprecated in API 33")
        override fun onCharacteristicRead(g: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) {
            if (g !== gatt) return
            @Suppress("DEPRECATION")
            pending?.offer(GattOutcome(status, characteristic.value?.copyOf()))
        }

        override fun onCharacteristicWrite(g: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) {
            if (g !== gatt) return
            pending?.offer(GattOutcome(status, null))
        }

        override fun onDescriptorWrite(g: BluetoothGatt, descriptor: BluetoothGattDescriptor, status: Int) {
            if (g !== gatt) return
            pending?.offer(GattOutcome(status, null))
        }

        override fun onCharacteristicChanged(
            g: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray,
        ) {
            if (g !== gatt) return
            deliverPdu(characteristic.uuid, value)
        }

        @Deprecated("Deprecated in API 33")
        override fun onCharacteristicChanged(g: BluetoothGatt, characteristic: BluetoothGattCharacteristic) {
            if (g !== gatt) return
            @Suppress("DEPRECATION")
            characteristic.value?.let { deliverPdu(characteristic.uuid, it) }
        }
    }

    private fun teardownOnDisconnect(g: BluetoothGatt, status: Int) {
        // A disconnect of the handle a connect is currently waiting on (it fires before [gatt] is
        // published) must release that connect awaiter -- but only for that handle, so a stale prior
        // attempt's disconnect can't wake a newer connect's slot.
        if (!isStaleConnectCallback(g)) connectPending?.offer(GattOutcome(status, null))
        if (gatt !== g) {
            // A stale handle disconnected (e.g. after a reconnect to a new device); just close it.
            closeClient(g)
            return
        }
        servicesReady = false
        serviceIndex = emptyMap()
        racpServiceUuids = emptySet()
        cancelWatchdog()
        handlers.clear()
        // `gatt === g` here, so this disconnect is for the live connection: failing its in-flight op is
        // correct. (A concurrent op-thread timeout would have already replaced [gatt], taking the early
        // return above, so it can't be redirected to a newer op's slot.)
        pending?.offer(GattOutcome(status, null))
        closeClient(g)
        gatt = null
        connectedAddress = null
    }

    private fun deliverPdu(characteristic: UUID, value: ByteArray) {
        Timber.v("GATT notification %s (%d bytes) %s", characteristic, value.size, MedtronicCodec.toHex(value))
        // Hop onto the connection manager's single worker thread so all onPdu callbacks are serialized
        // on one thread (AC3). Copy first: the API-33 callback may recycle its delivery buffer once this
        // returns, and the copy is read later on the worker.
        val copy = value.copyOf()
        worker.post { handlers[characteristic]?.onPdu?.invoke(copy) }
    }

    // -- Lifecycle ----------------------------------------------------------

    /**
     * Release the client GATT and the watchdog executor. Not part of the singleton's normal lifecycle
     * (the connection is reused across reads); provided for explicit teardown and tests.
     */
    fun close() {
        opLock.withLock { closeGatt() }
        watchdog.close()
    }

    // -- Logging ------------------------------------------------------------

    private fun logGattWarning(op: String, characteristic: UUID?, status: Int) {
        // AC7: WARN is forwarded to the glycemicgpt-mobile Sentry project, so it carries only the
        // operation + GATT status -- never a characteristic payload/value. The (non-PHI) characteristic
        // UUID and full detail stay at DEBUG (local logcat), below the Sentry threshold.
        Timber.w("Medtronic GATT %s failed (status=%s)", op, gattStatusName(status))
        Timber.d("Medtronic GATT %s detail: characteristic=%s status=%d", op, characteristic, status)
    }

    private fun logOperationFailure(op: String, characteristic: UUID, e: Throwable) {
        Timber.w("Medtronic GATT %s failed: %s", op, e.javaClass.simpleName)
        Timber.d(e, "Medtronic GATT %s failure detail: characteristic=%s", op, characteristic)
    }

    /** Number of live notification subscriptions; exposed for the transport's unit tests only. */
    internal fun activeSubscriptionCount(): Int = handlers.size

    private data class ResolvedChar(val serviceUuid: UUID, val characteristic: BluetoothGattCharacteristic)

    private class ActiveSubscription(
        val resolved: ResolvedChar,
        val onPdu: (ByteArray) -> Unit,
        val ownerGatt: BluetoothGatt,
    )

    private class GattOutcome(val status: Int, val value: ByteArray?)

    companion object {
        /** Per-GATT-operation timeout: a single read/write/CCCD round trip of 20-byte PDUs is quick. */
        const val DEFAULT_OPERATION_TIMEOUT_MS = 10_000L

        /** Connect + service-discovery timeout. */
        const val DEFAULT_CONNECT_TIMEOUT_MS = 10_000L

        /**
         * The report/control-point characteristics the read layer is allowed to write to. Everything
         * else is rejected by [write] -- the transport is READ-ONLY and never issues a therapeutic write.
         */
        private val WRITABLE_CONTROL_POINTS = setOf(
            MedtronicProtocol.RACP_UUID,
            MedtronicProtocol.CGM_SOCP_UUID,
            MedtronicProtocol.IDD_SRCP_UUID,
        )

        // CCCD payloads per the Bluetooth Core spec (Client Characteristic Configuration). Defined
        // here rather than via BluetoothGattDescriptor.* because those platform constants are null
        // under the unit-test android.jar stub (this module uses mockk, not Robolectric).
        private val CCCD_ENABLE_NOTIFICATION = byteArrayOf(0x01, 0x00)
        private val CCCD_ENABLE_INDICATION = byteArrayOf(0x02, 0x00)
        private val CCCD_DISABLE = byteArrayOf(0x00, 0x00)

        /** Synthetic status for a local timeout (not a platform GATT status). */
        private const val SYNTHETIC_TIMEOUT_STATUS = -1

        /** Synthetic status for an op the stack refused to start. */
        private const val SYNTHETIC_REJECTED_STATUS = -2

        /** Human-readable GATT status for WARN logs (no PHI -- a numeric stack code). */
        private fun gattStatusName(status: Int): String = when (status) {
            BluetoothGatt.GATT_SUCCESS -> "SUCCESS"
            0x02 -> "READ_NOT_PERMITTED"
            0x03 -> "WRITE_NOT_PERMITTED"
            0x05 -> "INSUFFICIENT_AUTHENTICATION"
            0x06 -> "REQUEST_NOT_SUPPORTED"
            0x07 -> "INVALID_OFFSET"
            0x08 -> "INSUFFICIENT_ENCRYPTION"
            0x0D -> "INVALID_ATTRIBUTE_LENGTH"
            0x13 -> "CONN_TERMINATE_PEER_USER"
            0x16 -> "CONN_TERMINATE_LOCAL_HOST"
            0x22 -> "CONN_FAILED_ESTABLISHMENT"
            0x3E -> "CONN_TIMEOUT"
            0x85 -> "GATT_ERROR"
            SYNTHETIC_TIMEOUT_STATUS -> "LOCAL_TIMEOUT"
            SYNTHETIC_REJECTED_STATUS -> "LOCAL_REJECTED"
            else -> "UNKNOWN_0x${status.toString(16)}"
        }
    }
}

/**
 * The off-thread mechanism for GATT-client subscription cleanup (AC4): a one-shot delayed timer (the
 * dangling-subscription watchdog) plus immediate off-caller-thread execution (so an `unsubscribe`
 * issued from a notification handler doesn't block the shared worker thread on its CCCD round trip).
 * Abstracted like [SerialWorker] so both paths are deterministically unit-testable without a real
 * timer thread.
 */
interface SubscriptionWatchdog {
    /** Run [task] after [delayMs]; the returned handle cancels it if the subscription is released first. */
    fun schedule(delayMs: Long, task: () -> Unit): Handle

    /** Run [task] as soon as possible on the cleanup thread, off the calling thread. */
    fun execute(task: () -> Unit)

    /** Release any resources (e.g. the executor thread). Default no-op for in-memory test doubles. */
    fun close() {}

    /** Cancels a scheduled task. */
    fun interface Handle {
        fun cancel()
    }
}

/** Production [SubscriptionWatchdog] backed by a single daemon scheduled-executor thread. */
class ScheduledSubscriptionWatchdog(
    private val executor: ScheduledExecutorService = Executors.newSingleThreadScheduledExecutor { runnable ->
        Thread(runnable, "medtronic-gatt-watchdog").apply { isDaemon = true }
    },
) : SubscriptionWatchdog {
    override fun schedule(delayMs: Long, task: () -> Unit): SubscriptionWatchdog.Handle {
        val future = executor.schedule(task, delayMs, TimeUnit.MILLISECONDS)
        return SubscriptionWatchdog.Handle { future.cancel(false) }
    }

    override fun execute(task: () -> Unit) {
        executor.execute(task)
    }

    override fun close() {
        executor.shutdownNow()
    }
}
