/*
 * Phone-as-peripheral BLE connection manager for the Medtronic MiniMed 700-series read-only driver.
 *
 * GlycemicGPT code (GPL-3.0). This is the inverted-topology connection core that has no Tandem
 * equivalent to clone: the phone advertises as a "Mobile …" peripheral and the pump connects to it
 * as the central (medtronic-ble-reverse-engineering.md Sec. 3). It owns the connection lifecycle,
 * drives the SAKE handshake (Sec. 4) to a live encrypted session, and auto-reconnects to an
 * already-paired pump. The Android BLE plumbing it sits on top of is modelled on OpenMinimed's
 * JavaPumpConnector (GPL-3.0, used with permission).
 *
 * Scope (Milestone B2): connection + authentication + reconnect only. The data readers (CGM/IOB/
 * history) and the MedtronicDevicePlugin / Hilt registration that consume this manager land in
 * Milestone C. Over-the-air validation against a real pump rides with 48.A2 / Milestone F -- nothing
 * here is claimed live-verified.
 */
package com.glycemicgpt.mobile.ble.connection

import android.content.Context
import com.glycemicgpt.mobile.ble.sake.MedtronicSakeSession
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.model.DiscoveredDevice
import com.glycemicgpt.mobile.domain.pump.PumpCredentialProvider
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.launch
import org.openminimed.sake.Constants
import org.openminimed.sake.KeyDatabase
import timber.log.Timber

/**
 * A connection fault surfaced alongside [MedtronicBleConnectionManager.connectionState] to explain
 * *why* a connection is not progressing -- in particular the single-peer condition (the pump only
 * talks to one phone at a time, so it must be removed from the official app first; Sec. 7).
 */
enum class MedtronicConnectionFault {
    /** This device cannot advertise as a BLE peripheral, so it can never pair (Sec. 3). */
    PERIPHERAL_UNSUPPORTED,

    /** The BLE advertiser rejected the advertisement (e.g. too many advertisers active). */
    ADVERTISE_FAILED,

    /** The pump connected but the SAKE handshake did not complete within the timeout. */
    HANDSHAKE_TIMEOUT,

    /** The SAKE handshake ran but authentication failed (CMAC/permit verification). */
    AUTH_FAILED,

    /**
     * First-pair advertising has been running with no pump connecting -- the pump is likely still
     * bound to another phone (e.g. the official Medtronic app) and must be removed from it first.
     * Working assumption from desk research; exact live behavior is confirmed in 48.A2 (Sec. 7).
     */
    BOUND_ELSEWHERE_SUSPECTED,
}

/**
 * Selects the advertising mode for a connection attempt. Already-paired pumps reconnect via the
 * `0xFE81` service ([AdvertisingMode.RECONNECT]); everything else is a first pairing via `0xFE82`.
 * Pure logic, separated out so the reconnect-service selection (AC5) is directly unit-testable.
 */
internal fun advertisingModeFor(paired: Boolean, forceFirstPair: Boolean): AdvertisingMode =
    if (paired && !forceFirstPair) AdvertisingMode.RECONNECT else AdvertisingMode.FIRST_PAIR

/**
 * Manages the phone-as-peripheral BLE connection to a Medtronic 700-series pump.
 *
 * Responsibilities:
 *  - Advertise as a "Mobile …" peripheral + stand up the read-only GATT server (delegated to
 *    [MedtronicPeripheral]).
 *  - Drive the SAKE handshake on a worker thread (delegated to [SakeHandshakeDriver]).
 *  - Expose the connection lifecycle as [connectionState] and the reason for a stall as [fault].
 *  - Auto-reconnect to an already-paired pump and persist pairing via [PumpCredentialProvider].
 *
 * Inject the collaborators for tests (the BLE layer is mocked); on-device, use the [Context]
 * secondary constructor which wires the real Android peripheral + a HandlerThread worker.
 */
class MedtronicBleConnectionManager(
    private val peripheral: MedtronicPeripheral,
    private val credentialStore: PumpCredentialProvider,
    private val worker: SerialWorker,
    private val scope: CoroutineScope,
    private val keyDatabase: KeyDatabase = Constants.KEYDB_PUMP_EXTRACTED,
    private val localName: String = DEFAULT_LOCAL_NAME,
    private val handshakeTimeoutMs: Long = DEFAULT_HANDSHAKE_TIMEOUT_MS,
    private val pairingWaitMs: Long = DEFAULT_PAIRING_WAIT_MS,
) {

    /** On-device constructor: real Android peripheral + dedicated SAKE worker thread. */
    constructor(context: Context, credentialStore: PumpCredentialProvider) : this(
        peripheral = AndroidMedtronicPeripheral(context),
        credentialStore = credentialStore,
        worker = HandlerThreadSerialWorker(SAKE_WORKER_THREAD_NAME),
        scope = CoroutineScope(SupervisorJob() + Dispatchers.IO),
    )

    private val _connectionState = MutableStateFlow(ConnectionState.DISCONNECTED)

    /** Observable BLE/auth connection lifecycle. */
    val connectionState: StateFlow<ConnectionState> = _connectionState.asStateFlow()

    private val _fault = MutableStateFlow<MedtronicConnectionFault?>(null)

    /** The reason the connection is not progressing, or `null` when there is nothing to report. */
    val fault: StateFlow<MedtronicConnectionFault?> = _fault.asStateFlow()

    /** The live SAKE session after a successful handshake -- the read layer (Milestone C) decrypts with it. */
    @Volatile
    var sakeSession: MedtronicSakeSession? = null
        private set

    @Volatile
    private var autoReconnect = false

    @Volatile
    private var connectedAddress: String? = null

    @Volatile
    private var onDiscovered: ((DiscoveredDevice) -> Unit)? = null

    // All connection-lifecycle state below is confined to the SerialWorker thread: every public
    // entry point and every BLE callback hops onto [worker] before touching it, so the check-then-set
    // transitions run on a single thread with no locking (the same discipline SakeHandshakeDriver
    // uses). The fields stay @Volatile so the read layer / UI can still observe the latest value.
    @Volatile
    private var authTimeoutJob: Job? = null

    @Volatile
    private var pairingWaitJob: Job? = null

    private val handshakeListener = object : SakeHandshakeDriver.HandshakeListener {
        // Invoked on the worker thread already (the driver runs on [worker]).
        override fun onAuthenticated(session: MedtronicSakeSession) = onHandshakeComplete(session)
        override fun onAuthFailed(cause: Throwable?) = onHandshakeFailed(cause)
    }

    private val driver = SakeHandshakeDriver(
        worker = worker,
        sessionFactory = { MedtronicSakeSession(keyDatabase) },
        notifySink = peripheral::sendSakeNotification,
        listener = handshakeListener,
    )

    // BLE callbacks arrive on the binder thread; hop onto the worker so all lifecycle mutation is
    // serialized with the handshake. onSakeUnsubscribed/onSakeWrite already post via the driver.
    private val peripheralListener = object : PeripheralListener {
        override fun onAdvertiseStarted(mode: AdvertisingMode) = worker.post { onAdvertising(mode) }
        override fun onAdvertiseFailed(errorCode: Int) = worker.post { onAdvertisingFailed(errorCode) }
        override fun onPumpConnected(address: String) = worker.post { onCentralConnected(address) }
        override fun onSakeSubscribed() = worker.post { startAuthentication() }
        override fun onSakeUnsubscribed() = driver.onUnsubscribed()
        override fun onSakeWrite(value: ByteArray) = driver.onPumpWrite(value)
        override fun onPumpDisconnected(status: Int) = worker.post { onCentralDisconnected(status) }
    }

    // -- Public lifecycle ---------------------------------------------------

    /**
     * Begin a connection: advertise + stand up the GATT server and wait for the pump to connect and
     * complete SAKE. Picks [AdvertisingMode.RECONNECT] for an already-paired pump unless
     * [forceFirstPair] is set (e.g. the user is re-pairing). No-op if the device cannot advertise as
     * a peripheral.
     */
    fun startSession(forceFirstPair: Boolean = false) = worker.post {
        if (!ensureSupported()) return@post
        val mode = advertisingModeFor(credentialStore.isPaired(), forceFirstPair)
        autoReconnect = true
        beginAdvertising(mode, ConnectionState.CONNECTING)
    }

    /** Auto-reconnect to a previously paired pump. No-op if no pump is paired. */
    fun reconnectIfPaired() = worker.post {
        if (!credentialStore.isPaired()) {
            Timber.d("reconnectIfPaired: no paired pump")
            return@post
        }
        if (!ensureSupported()) return@post
        autoReconnect = true
        beginAdvertising(AdvertisingMode.RECONNECT, ConnectionState.CONNECTING)
    }

    /** Stop advertising + reconnect and drop the session, but keep the pairing. Safe to call when idle. */
    fun disconnect() = worker.post {
        autoReconnect = false
        teardown(ConnectionState.DISCONNECTED, fault = null)
    }

    /** Clear the pairing, remove the BLE bond, and disconnect. */
    fun unpair() = worker.post {
        val address = credentialStore.getPairedAddress() ?: connectedAddress
        autoReconnect = false
        teardown(ConnectionState.DISCONNECTED, fault = null)
        credentialStore.clearPairing()
        val bondRemoved = if (address != null) peripheral.removeBond(address) else false
        Timber.d("Medtronic pump unpaired; credentials cleared, bondRemoved=%b", bondRemoved)
    }

    /**
     * Discovery in the inverted topology. There is **no active central scan** here -- the pump is
     * the central and *it* finds *us*, so discovery is advertise-and-wait: this starts first-pair
     * advertising and emits a [DiscoveredDevice] when a pump connects to the GATT server. Cancelling
     * collection stops advertising if no pump has connected yet. The connection that a discovered
     * pump initiates then proceeds straight into the SAKE handshake (the central cannot be made to
     * "connect later" the way an active scan implies). C wires this into `DevicePlugin.scan()`.
     */
    fun scan(): Flow<DiscoveredDevice> = callbackFlow {
        if (!peripheral.isSupported()) {
            Timber.e("BLE peripheral advertising not supported; cannot scan")
            worker.post { _fault.value = MedtronicConnectionFault.PERIPHERAL_UNSUPPORTED }
            close()
            return@callbackFlow
        }
        onDiscovered = { trySend(it) }
        worker.post {
            autoReconnect = false
            beginAdvertising(AdvertisingMode.FIRST_PAIR, ConnectionState.SCANNING)
        }
        awaitClose {
            onDiscovered = null
            worker.post {
                // Only tear down if discovery was cancelled before a pump actually connected; once a
                // pump is connecting/authenticating the session owns the lifecycle, not the scan.
                if (_connectionState.value == ConnectionState.SCANNING) {
                    teardown(ConnectionState.DISCONNECTED, fault = null)
                }
            }
        }
    }

    /** Release the worker thread and cancel the scope. The manager is unusable afterwards. */
    fun close() {
        // Tear down synchronously on the caller thread: the worker is about to stop, so a posted
        // teardown could be dropped before it runs.
        autoReconnect = false
        cancelTimers()
        resetSessionState()
        peripheral.stop()
        _fault.value = null
        _connectionState.value = ConnectionState.DISCONNECTED
        worker.stop()
        scope.cancel()
    }

    // -- Advertising / peripheral callbacks ---------------------------------

    private fun beginAdvertising(mode: AdvertisingMode, state: ConnectionState) {
        cancelTimers()
        resetSessionState()
        _fault.value = null
        _connectionState.value = state
        Timber.d("Advertising as '%s' in %s mode", localName, mode)
        peripheral.start(mode, localName, peripheralListener)
    }

    /** Drop the live session, the remembered peer, and arm a fresh handshake. */
    private fun resetSessionState() {
        sakeSession = null
        connectedAddress = null
        driver.reset()
    }

    private fun onAdvertising(mode: AdvertisingMode) {
        Timber.d("Advertising started (%s)", mode)
        // First-pair single-peer detection (Sec. 7): if no pump connects in the window, the pump is
        // probably still bound to another phone. Reconnect mode waits indefinitely because the pump
        // scans infrequently. TODO(48.A2): tune/confirm this window against a real pump.
        if (mode == AdvertisingMode.FIRST_PAIR) armPairingWaitTimer()
    }

    private fun onAdvertisingFailed(errorCode: Int) {
        Timber.e("Advertising failed (errorCode=%d)", errorCode)
        autoReconnect = false
        teardown(ConnectionState.DISCONNECTED, fault = MedtronicConnectionFault.ADVERTISE_FAILED)
    }

    private fun onCentralConnected(address: String) {
        Timber.i("Pump connected: %s", address)
        pairingWaitJob?.cancel()
        pairingWaitJob = null
        _fault.value = null
        connectedAddress = address
        // Single-peer: stop advertising so no second central can connect mid-handshake (Sec. 7).
        peripheral.stopAdvertising()
        // A pump connecting from any advertising state (first pair, scan, or reconnect) is "connected,
        // pre-auth"; AUTHENTICATING/CONNECTED are reached via onSakeSubscribed/handshake completion.
        when (_connectionState.value) {
            ConnectionState.SCANNING,
            ConnectionState.CONNECTING,
            ConnectionState.RECONNECTING -> _connectionState.value = ConnectionState.CONNECTING
            else -> Unit
        }
        onDiscovered?.invoke(
            DiscoveredDevice(
                name = localName,
                address = address,
                pluginId = PLUGIN_ID,
            ),
        )
    }

    private fun startAuthentication() {
        Timber.d("Pump subscribed to SAKE; starting handshake")
        _connectionState.value = ConnectionState.AUTHENTICATING
        armAuthTimeout()
        driver.onSubscribed()
    }

    private fun onCentralDisconnected(status: Int) {
        Timber.w("Pump disconnected (status=%d)", status)
        cancelTimers()
        resetSessionState()

        // A terminal auth failure latches AUTH_FAILED; the inevitable disconnect must not reset it
        // or kick off a reconnect loop against a pump that just rejected us.
        if (_connectionState.value == ConnectionState.AUTH_FAILED) {
            peripheral.stopAdvertising()
            return
        }

        if (autoReconnect && credentialStore.isPaired()) {
            _connectionState.value = ConnectionState.RECONNECTING
            Timber.d("Re-advertising for reconnect (%s)", AdvertisingMode.RECONNECT)
            peripheral.advertise(AdvertisingMode.RECONNECT, localName)
        } else {
            teardown(ConnectionState.DISCONNECTED, fault = null)
        }
    }

    // -- Handshake callbacks (worker thread) --------------------------------

    private fun onHandshakeComplete(session: MedtronicSakeSession) {
        authTimeoutJob?.cancel()
        authTimeoutJob = null
        sakeSession = session
        _fault.value = null
        // Persist the pairing. SAKE has no pairing code (authentication is the static-key handshake
        // plus the OS BLE bond), so the credential "code" slot records the advertised identity.
        connectedAddress?.let { credentialStore.savePairing(it, localName) }
        _connectionState.value = ConnectionState.CONNECTED
        Timber.i("Pump authenticated; session ready")
    }

    private fun onHandshakeFailed(cause: Throwable?) {
        authTimeoutJob?.cancel()
        authTimeoutJob = null
        sakeSession = null
        autoReconnect = false
        // Stop attracting the pump; the user must re-pair. Matches the handshake-timeout path. The
        // GATT server stays open (the pump will drop the link; onCentralDisconnected keeps AUTH_FAILED).
        peripheral.stopAdvertising()
        _fault.value = MedtronicConnectionFault.AUTH_FAILED
        _connectionState.value = ConnectionState.AUTH_FAILED
        Timber.e(cause, "SAKE authentication failed")
    }

    // -- Timers -------------------------------------------------------------

    private fun armAuthTimeout() {
        authTimeoutJob?.cancel()
        // The delay runs on [scope]; the check-then-set hops back onto the worker so it is serialized
        // with onHandshakeComplete -- the guard then can't flip an already-CONNECTED session.
        authTimeoutJob = scope.launch {
            delay(handshakeTimeoutMs)
            worker.post {
                if (_connectionState.value == ConnectionState.AUTHENTICATING) {
                    Timber.e("SAKE handshake timed out after %d ms", handshakeTimeoutMs)
                    _fault.value = MedtronicConnectionFault.HANDSHAKE_TIMEOUT
                    _connectionState.value = ConnectionState.AUTH_FAILED
                    autoReconnect = false
                    peripheral.stopAdvertising()
                }
            }
        }
    }

    private fun armPairingWaitTimer() {
        pairingWaitJob?.cancel()
        pairingWaitJob = scope.launch {
            delay(pairingWaitMs)
            worker.post {
                val state = _connectionState.value
                if (state == ConnectionState.CONNECTING || state == ConnectionState.SCANNING) {
                    Timber.w("No pump connected after %d ms; pump may be bound to another phone", pairingWaitMs)
                    _fault.value = MedtronicConnectionFault.BOUND_ELSEWHERE_SUSPECTED
                }
            }
        }
    }

    private fun cancelTimers() {
        authTimeoutJob?.cancel()
        authTimeoutJob = null
        pairingWaitJob?.cancel()
        pairingWaitJob = null
    }

    // -- Helpers ------------------------------------------------------------

    private fun ensureSupported(): Boolean {
        if (peripheral.isSupported()) return true
        Timber.e("BLE peripheral advertising not supported on this device")
        _fault.value = MedtronicConnectionFault.PERIPHERAL_UNSUPPORTED
        _connectionState.value = ConnectionState.DISCONNECTED
        return false
    }

    private fun teardown(state: ConnectionState, fault: MedtronicConnectionFault?) {
        cancelTimers()
        resetSessionState()
        peripheral.stop()
        _fault.value = fault
        _connectionState.value = state
    }

    companion object {
        /** Default advertised local name. Must match `Mobile .{0,7}`. TODO(48.A2/D): per-install identity. */
        const val DEFAULT_LOCAL_NAME = "Mobile 000001"

        /** Plugin id stamped on discovered devices. The MedtronicDevicePlugin (Milestone C) owns the canonical id. */
        const val PLUGIN_ID = "medtronic"

        private const val SAKE_WORKER_THREAD_NAME = "medtronic-sake"

        /** SAKE has six round trips of 20-byte frames; 30s is generous even on a slow BLE link. */
        private const val DEFAULT_HANDSHAKE_TIMEOUT_MS = 30_000L

        /** First-pair window before suspecting the pump is bound to another phone (Sec. 7). */
        private const val DEFAULT_PAIRING_WAIT_MS = 60_000L
    }
}
