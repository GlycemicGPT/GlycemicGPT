/*
 * AC1-AC8: unit tests for the on-device BluetoothGatt-client transport against a mocked BluetoothGatt /
 * BluetoothGattCallback (mockk -- no Robolectric, mirroring the rest of this module). The mocked GATT
 * fires its callbacks synchronously from each operation so the transport's blocking, latch-based
 * operation model completes deterministically on the test thread; a queueing worker lets a test prove
 * inbound PDUs are hopped onto the worker rather than delivered inline. No real pump and no Android BLE
 * stack are involved -- over-the-air validation is 48.A2 / Milestone F.
 */
package com.glycemicgpt.mobile.ble.connection

import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothGattService
import android.bluetooth.BluetoothProfile
import android.content.Context
import android.util.Log
import com.glycemicgpt.mobile.ble.protocol.MedtronicProtocol
import com.glycemicgpt.mobile.ble.read.MedtronicReadException
import io.mockk.every
import io.mockk.mockk
import io.mockk.slot
import io.mockk.verify
import java.util.UUID
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import timber.log.Timber

class AndroidMedtronicGattLinkTest {

    private val context = mockk<Context>(relaxed = true)
    private val device = mockk<BluetoothDevice>(relaxed = true)
    private val gatt = mockk<BluetoothGatt>(relaxed = true)
    private val callbackSlot = slot<BluetoothGattCallback>()
    private val callback: BluetoothGattCallback get() = callbackSlot.captured

    private val readValues = mutableMapOf<UUID, ByteArray>()
    private val events = mutableListOf<String>()
    private val watchdog = ManualWatchdog()

    // -- GATT table the mocked pump exposes ---------------------------------

    private val cgmFeature = characteristic(MedtronicProtocol.CGM_FEATURE_UUID, withCccd = false)
    private val cgmMeasurement = characteristic(MedtronicProtocol.CGM_MEASUREMENT_UUID, BluetoothGattCharacteristic.PROPERTY_NOTIFY)
    private val cgmRacp = characteristic(MedtronicProtocol.RACP_UUID, BluetoothGattCharacteristic.PROPERTY_INDICATE)
    private val iddFeatures = characteristic(MedtronicProtocol.IDD_FEATURES_UUID, withCccd = false)
    private val iddHistory = characteristic(MedtronicProtocol.IDD_HISTORY_DATA_UUID, BluetoothGattCharacteristic.PROPERTY_NOTIFY)
    private val iddRacp = characteristic(MedtronicProtocol.RACP_UUID, BluetoothGattCharacteristic.PROPERTY_INDICATE)
    private val batteryLevel = characteristic(MedtronicProtocol.BATTERY_LEVEL_UUID, withCccd = false)

    private val cgmService = service(MedtronicProtocol.CGM_SERVICE_UUID, cgmFeature, cgmMeasurement, cgmRacp)
    private val iddService = service(MedtronicProtocol.IDD_SERVICE_UUID, iddFeatures, iddHistory, iddRacp)
    private val batteryService = service(MedtronicProtocol.BATTERY_SERVICE_UUID, batteryLevel)

    /** GATT statuses the mock reports; overridden per test to exercise the failure paths. */
    private var readStatus = BluetoothGatt.GATT_SUCCESS
    private var writeStatus = BluetoothGatt.GATT_SUCCESS
    private var descriptorStatus = BluetoothGatt.GATT_SUCCESS

    // The client(s) `connectGatt` hands back, in order; defaults to the single shared [gatt].
    private val connectQueue = ArrayDeque<BluetoothGatt>()

    init {
        every { device.address } returns PUMP_ADDRESS
        every { device.connectGatt(any(), any(), capture(callbackSlot), any()) } answers {
            // Simulate the stack connecting + discovering synchronously off the connectGatt call.
            val client = if (connectQueue.isEmpty()) gatt else connectQueue.removeFirst()
            callback.onConnectionStateChange(client, BluetoothGatt.GATT_SUCCESS, BluetoothProfile.STATE_CONNECTED)
            client
        }
        stubGattClient(gatt)
    }

    /** Stub a `BluetoothGatt` client so its callbacks fire synchronously off each operation. */
    private fun stubGattClient(client: BluetoothGatt) {
        every { client.services } returns listOf(cgmService, iddService, batteryService)
        every { client.discoverServices() } answers {
            callback.onServicesDiscovered(client, BluetoothGatt.GATT_SUCCESS)
            true
        }
        every { client.setCharacteristicNotification(any(), any()) } returns true
        every { client.readCharacteristic(any()) } answers {
            val char = firstArg<BluetoothGattCharacteristic>()
            callback.onCharacteristicRead(client, char, readValues[char.uuid] ?: ByteArray(0), readStatus)
            true
        }
        @Suppress("DEPRECATION")
        every { client.writeCharacteristic(any<BluetoothGattCharacteristic>()) } answers {
            val char = firstArg<BluetoothGattCharacteristic>()
            events.add("write-char:${char.uuid}")
            callback.onCharacteristicWrite(client, char, writeStatus)
            true
        }
        @Suppress("DEPRECATION")
        every { client.writeDescriptor(any<BluetoothGattDescriptor>()) } answers {
            events.add("write-cccd")
            callback.onDescriptorWrite(client, firstArg(), descriptorStatus)
            true
        }
    }

    private fun newLink(worker: SerialWorker = DirectSerialWorker()) = AndroidMedtronicGattLink(
        context = context,
        deviceProvider = { device },
        worker = worker,
        watchdog = watchdog,
    )

    @After
    fun tearDown() = Timber.uprootAll()

    // -- AC1 / AC5: connect, discover, read; never requestMtu ---------------

    @Test
    fun `connects discovers and reads a static characteristic`() {
        readValues[MedtronicProtocol.BATTERY_LEVEL_UUID] = byteArrayOf(85)

        val value = newLink().read(MedtronicProtocol.BATTERY_LEVEL_UUID)

        assertArrayEquals(byteArrayOf(85), value)
        verify { device.connectGatt(any(), false, any(), BluetoothDevice.TRANSPORT_LE) }
        verify { gatt.discoverServices() }
        verify(exactly = 0) { gatt.requestMtu(any()) }
    }

    @Test
    fun `opens the client connection only once across reads`() {
        readValues[MedtronicProtocol.BATTERY_LEVEL_UUID] = byteArrayOf(85)
        val link = newLink()

        link.read(MedtronicProtocol.BATTERY_LEVEL_UUID)
        link.read(MedtronicProtocol.BATTERY_LEVEL_UUID)

        verify(exactly = 1) { device.connectGatt(any(), any(), any(), any()) }
    }

    @Test
    fun `read skips cleanly when no pump device is available`() {
        val link = AndroidMedtronicGattLink(context, deviceProvider = { null }, worker = DirectSerialWorker(), watchdog = watchdog)

        val error = assertThrows(MedtronicReadException::class.java) {
            link.read(MedtronicProtocol.BATTERY_LEVEL_UUID)
        }
        assertTrue(error.message!!.contains("not connected"))
    }

    // -- AC3: notifications effective (CCCD written) before the control-point write --

    @Test
    fun `subscribe enables the CCCD before the subsequent control-point write`() {
        val link = newLink()

        link.subscribe(MedtronicProtocol.CGM_MEASUREMENT_UUID) {}
        link.write(MedtronicProtocol.RACP_UUID, byteArrayOf(0x01, 0x06))

        assertEquals(listOf("write-cccd", "write-char:${MedtronicProtocol.RACP_UUID}"), events)
    }

    // -- AC3: inbound PDUs are delivered serialized on the connection manager's worker thread --

    @Test
    fun `inbound notifications are delivered on the worker thread not inline`() {
        val queueingWorker = QueueingWorker()
        val link = newLink(worker = queueingWorker)
        val received = mutableListOf<ByteArray>()
        link.subscribe(MedtronicProtocol.CGM_MEASUREMENT_UUID) { received.add(it) }

        callback.onCharacteristicChanged(gatt, cgmMeasurement, byteArrayOf(0x0e, 0x01))
        assertTrue("delivery must be posted to the worker, not run inline on the binder thread", received.isEmpty())

        queueingWorker.runQueued()
        assertEquals(1, received.size)
        assertArrayEquals(byteArrayOf(0x0e, 0x01), received[0])
    }

    // -- AC2: the shared 0x2A52 RACP is scoped to the right service ----------

    @Test
    fun `RACP is scoped to the CGM service for a CGM exchange`() {
        val link = newLink()

        link.subscribe(MedtronicProtocol.CGM_MEASUREMENT_UUID) {}
        link.write(MedtronicProtocol.RACP_UUID, byteArrayOf(0x01, 0x06))

        @Suppress("DEPRECATION")
        verify { gatt.writeCharacteristic(cgmRacp) }
        @Suppress("DEPRECATION")
        verify(exactly = 0) { gatt.writeCharacteristic(iddRacp) }
    }

    @Test
    fun `RACP is scoped to the IDD service for a history exchange`() {
        val link = newLink()

        link.subscribe(MedtronicProtocol.IDD_HISTORY_DATA_UUID) {}
        link.write(MedtronicProtocol.RACP_UUID, byteArrayOf(0x33, 0x69, 0x0f))

        @Suppress("DEPRECATION")
        verify { gatt.writeCharacteristic(iddRacp) }
        @Suppress("DEPRECATION")
        verify(exactly = 0) { gatt.writeCharacteristic(cgmRacp) }
    }

    @Test
    fun `RACP falls back to the most recently read RACP-bearing service, unpoisoned by a battery read`() {
        val link = newLink()

        // IDD read establishes IDD context; a Battery read (no RACP) must NOT move it; a bare RACP
        // write with no active data subscription then still resolves to the IDD service's RACP.
        link.read(MedtronicProtocol.IDD_FEATURES_UUID)
        link.read(MedtronicProtocol.BATTERY_LEVEL_UUID)
        link.write(MedtronicProtocol.RACP_UUID, byteArrayOf(0x5a, 0x33, 0x0f))

        @Suppress("DEPRECATION")
        verify { gatt.writeCharacteristic(iddRacp) }
        @Suppress("DEPRECATION")
        verify(exactly = 0) { gatt.writeCharacteristic(cgmRacp) }
    }

    // -- READ-ONLY: writes are confined to the report/control points ---------

    @Test
    fun `write to a non-control-point characteristic is refused`() {
        val link = newLink()

        link.write(MedtronicProtocol.CGM_MEASUREMENT_UUID, byteArrayOf(0x01))

        @Suppress("DEPRECATION")
        verify(exactly = 0) { gatt.writeCharacteristic(any<BluetoothGattCharacteristic>()) }
        verify(exactly = 0) { device.connectGatt(any(), any(), any(), any()) }
    }

    // -- Connection-state failure edges --------------------------------------

    @Test
    fun `a GATT error on connect surfaces as a failed read and leaves no stale link`() {
        every { device.connectGatt(any(), any(), capture(callbackSlot), any()) } answers {
            // Connection establishment failed (e.g. GATT 133): the stack reports DISCONNECTED with the
            // error status rather than CONNECTED.
            callback.onConnectionStateChange(gatt, GATT_ERROR_133, BluetoothProfile.STATE_DISCONNECTED)
            gatt
        }
        val link = newLink()

        assertThrows(MedtronicReadException::class.java) {
            link.read(MedtronicProtocol.BATTERY_LEVEL_UUID)
        }
        assertEquals(0, link.activeSubscriptionCount())
    }

    @Test
    fun `an unexpected disconnect invalidates the cached link so the next read reconnects`() {
        readValues[MedtronicProtocol.BATTERY_LEVEL_UUID] = byteArrayOf(85)
        val link = newLink()

        link.read(MedtronicProtocol.BATTERY_LEVEL_UUID) // opens connection #1
        // The pump drops the link mid-session.
        callback.onConnectionStateChange(gatt, GATT_CONN_TERMINATE_PEER_USER, BluetoothProfile.STATE_DISCONNECTED)
        link.read(MedtronicProtocol.BATTERY_LEVEL_UUID) // must re-establish, not reuse the dead link

        verify(exactly = 2) { device.connectGatt(any(), any(), any(), any()) }
    }

    @Test
    fun `subscribe aborts without writing the CCCD when setCharacteristicNotification is rejected`() {
        every { gatt.setCharacteristicNotification(any(), any()) } returns false
        val link = newLink()

        link.subscribe(MedtronicProtocol.CGM_MEASUREMENT_UUID) {}

        assertEquals(0, link.activeSubscriptionCount())
        @Suppress("DEPRECATION")
        verify(exactly = 0) { gatt.writeDescriptor(any<BluetoothGattDescriptor>()) }
    }

    // -- AC4: a timed-out (cancelled) subscribe leaves no dangling subscription --

    @Test
    fun `the watchdog releases dangling subscriptions and stops delivering notifications`() {
        val link = newLink()
        val received = mutableListOf<ByteArray>()
        link.subscribe(MedtronicProtocol.CGM_MEASUREMENT_UUID) { received.add(it) }
        link.subscribe(MedtronicProtocol.RACP_UUID) { received.add(it) }
        assertEquals(2, link.activeSubscriptionCount())

        // The driving coroutine was cancelled by the gateway timeout without the reader unsubscribing.
        watchdog.fire()

        assertEquals(0, link.activeSubscriptionCount())
        callback.onCharacteristicChanged(gatt, cgmMeasurement, byteArrayOf(0x0e))
        assertTrue("a released subscription must not deliver notifications", received.isEmpty())
    }

    @Test
    fun `unsubscribe cancels the watchdog once the last subscription is released`() {
        val link = newLink()
        link.subscribe(MedtronicProtocol.CGM_MEASUREMENT_UUID) {}

        link.unsubscribe(MedtronicProtocol.CGM_MEASUREMENT_UUID)

        assertEquals(0, link.activeSubscriptionCount())
        assertTrue(watchdog.cancelled)
    }

    @Test
    fun `unsubscribe disables the CCCD off the worker thread`() {
        // A reader calls unsubscribe from inside its onPdu handler on the worker; the blocking CCCD
        // disable must not run on that worker. With a worker whose queue is never drained, the disable
        // still happens -- via the cleanup executor -- so it cannot have gone through the worker.
        val queueingWorker = QueueingWorker()
        val link = newLink(worker = queueingWorker)
        link.subscribe(MedtronicProtocol.CGM_MEASUREMENT_UUID) {} // writeDescriptor #1 = CCCD enable

        link.unsubscribe(MedtronicProtocol.CGM_MEASUREMENT_UUID) // writeDescriptor #2 = CCCD disable

        assertEquals(0, link.activeSubscriptionCount())
        @Suppress("DEPRECATION")
        verify(exactly = 2) { gatt.writeDescriptor(any<BluetoothGattDescriptor>()) }
    }

    @Test
    fun `a deferred unsubscribe does not disable a characteristic on a reconnected client`() {
        val gattB = mockk<BluetoothGatt>(relaxed = true)
        stubGattClient(gattB)
        readValues[MedtronicProtocol.BATTERY_LEVEL_UUID] = byteArrayOf(85)
        connectQueue.addAll(listOf(gatt, gattB)) // connection A then, after reconnect, B
        val deferring = DeferringWatchdog()
        val link = AndroidMedtronicGattLink(context, deviceProvider = { device }, worker = DirectSerialWorker(), watchdog = deferring)

        link.subscribe(MedtronicProtocol.CGM_MEASUREMENT_UUID) {} // connects to A; CCCD enable on A; owner = A
        link.unsubscribe(MedtronicProtocol.CGM_MEASUREMENT_UUID) // queues the disable, deferred
        // A drops; the next read reconnects to B.
        callback.onConnectionStateChange(gatt, GATT_CONN_TERMINATE_PEER_USER, BluetoothProfile.STATE_DISCONNECTED)
        link.read(MedtronicProtocol.BATTERY_LEVEL_UUID)

        deferring.runDeferred() // the queued disable now runs against the live client (B)

        @Suppress("DEPRECATION")
        verify(exactly = 0) { gattB.writeDescriptor(any<BluetoothGattDescriptor>()) }
        verify(exactly = 0) { gattB.setCharacteristicNotification(any(), false) }
    }

    @Test
    fun `a failed CCCD enable leaves no phantom subscription`() {
        descriptorStatus = GATT_INSUFFICIENT_AUTHENTICATION
        val link = newLink()

        link.subscribe(MedtronicProtocol.CGM_MEASUREMENT_UUID) {}

        assertEquals(0, link.activeSubscriptionCount())
    }

    // -- AC7: BLE/GATT failures route through Timber.w with op + status, never payload --

    @Test
    fun `a read failure throws and surfaces the GATT status without the payload`() {
        val tree = RecordingTree().also { Timber.plant(it) }
        readStatus = GATT_INSUFFICIENT_AUTHENTICATION

        assertThrows(MedtronicReadException::class.java) {
            newLink().read(MedtronicProtocol.CGM_FEATURE_UUID)
        }

        assertTrue(tree.warns.any { it.contains("read") && it.contains("INSUFFICIENT_AUTHENTICATION") })
    }

    @Test
    fun `a write failure logs op and status at WARN but never the written payload`() {
        val tree = RecordingTree().also { Timber.plant(it) }
        writeStatus = GATT_INSUFFICIENT_AUTHENTICATION
        val payload = byteArrayOf(0x01, 0x06, 0x42)

        val link = newLink()
        link.subscribe(MedtronicProtocol.CGM_MEASUREMENT_UUID) {}
        link.write(MedtronicProtocol.RACP_UUID, payload)

        assertTrue(tree.warns.any { it.contains("write") && it.contains("INSUFFICIENT_AUTHENTICATION") })
        val payloadFragments = listOf("0106", "01 06", "[1,", "010642")
        assertFalse(
            "WARN logs must not embed the characteristic payload",
            tree.warns.any { warn -> payloadFragments.any { warn.contains(it) } },
        )
    }

    // -- Test doubles --------------------------------------------------------

    private fun characteristic(
        uuid: UUID,
        properties: Int = 0,
        withCccd: Boolean = true,
    ): BluetoothGattCharacteristic {
        val char = mockk<BluetoothGattCharacteristic>(relaxed = true)
        every { char.uuid } returns uuid
        every { char.properties } returns properties
        every { char.getDescriptor(MedtronicProtocol.CCCD_UUID) } returns
            if (withCccd) mockk(relaxed = true) else null
        return char
    }

    private fun service(uuid: UUID, vararg chars: BluetoothGattCharacteristic): BluetoothGattService {
        val service = mockk<BluetoothGattService>(relaxed = true)
        every { service.uuid } returns uuid
        every { service.characteristics } returns chars.toList()
        return service
    }

    /** A [SerialWorker] that defers posted tasks so a test can prove delivery is not run inline. */
    private class QueueingWorker : SerialWorker {
        private val queued = ArrayDeque<() -> Unit>()

        override fun post(task: () -> Unit) {
            queued.add(task)
        }

        override fun stop() = queued.clear()

        fun runQueued() {
            while (queued.isNotEmpty()) queued.removeFirst().invoke()
        }
    }

    /** A [SubscriptionWatchdog] whose scheduled task the test fires on demand (no real timer). */
    private class ManualWatchdog : SubscriptionWatchdog {
        private var task: (() -> Unit)? = null
        var cancelled = false
            private set

        override fun schedule(delayMs: Long, task: () -> Unit): SubscriptionWatchdog.Handle {
            this.task = task
            return SubscriptionWatchdog.Handle {
                cancelled = true
                this.task = null
            }
        }

        override fun execute(task: () -> Unit) = task()

        fun fire() = task?.invoke() ?: Unit
    }

    /** A [SubscriptionWatchdog] that defers `execute` work so a test can run it after a reconnect. */
    private class DeferringWatchdog : SubscriptionWatchdog {
        private var timerTask: (() -> Unit)? = null
        private val deferred = ArrayDeque<() -> Unit>()

        override fun schedule(delayMs: Long, task: () -> Unit): SubscriptionWatchdog.Handle {
            timerTask = task
            return SubscriptionWatchdog.Handle { timerTask = null }
        }

        override fun execute(task: () -> Unit) {
            deferred.add(task)
        }

        fun runDeferred() {
            while (deferred.isNotEmpty()) deferred.removeFirst().invoke()
        }
    }

    /** Records emitted Timber logs so a test can assert the WARN discipline (AC7). */
    private class RecordingTree : Timber.Tree() {
        val warns = mutableListOf<String>()

        override fun log(priority: Int, tag: String?, message: String, t: Throwable?) {
            if (priority == Log.WARN) warns.add(message)
        }
    }

    private companion object {
        const val PUMP_ADDRESS = "AA:BB:CC:DD:EE:FF"
        const val GATT_INSUFFICIENT_AUTHENTICATION = 0x05
        const val GATT_CONN_TERMINATE_PEER_USER = 0x13
        const val GATT_ERROR_133 = 0x85
    }
}
