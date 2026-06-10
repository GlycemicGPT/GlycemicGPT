/*
 * State-machine, reconnect, MTU-discipline and discovery tests for MedtronicBleConnectionManager.
 *
 * The Android BLE layer is mocked (mockk MedtronicPeripheral); the SAKE worker runs inline
 * (DirectSerialWorker) so a full handshake completes synchronously, and the pump is simulated with
 * SakeClient + the matched synthetic key-DB pair. No real pump and no Android BLE stack are
 * involved -- over-the-air validation is deferred to 48.A2 / Milestone F.
 */
package com.glycemicgpt.mobile.ble.connection

import com.glycemicgpt.mobile.ble.protocol.PduFramer
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.model.DiscoveredDevice
import io.mockk.every
import io.mockk.mockk
import io.mockk.slot
import io.mockk.verify
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.openminimed.sake.DeviceType
import org.openminimed.sake.SakeClient

@OptIn(ExperimentalCoroutinesApi::class)
class MedtronicBleConnectionManagerTest {

    private val notifications = mutableListOf<ByteArray>()
    private val credentialStore = FakeCredentialStore()
    private val peripheral = mockk<MedtronicPeripheral>(relaxUnitFun = true)
    private val listenerSlot = slot<PeripheralListener>()

    private val testScope = TestScope(StandardTestDispatcher())

    init {
        every { peripheral.isSupported() } returns true
        every { peripheral.start(any(), any(), capture(listenerSlot)) } returns Unit
        every { peripheral.sendSakeNotification(any()) } answers { notifications.add(firstArg()); true }
        every { peripheral.removeBond(any()) } returns true
    }

    private val listener: PeripheralListener get() = listenerSlot.captured

    private fun newManager(
        scope: CoroutineScope = testScope,
        handshakeTimeoutMs: Long = 30_000L,
        pairingWaitMs: Long = 60_000L,
    ) = MedtronicBleConnectionManager(
        peripheral = peripheral,
        credentialStore = credentialStore,
        worker = DirectSerialWorker(),
        scope = scope,
        keyDatabase = SakeVectors.customServerKeyDb(),
        handshakeTimeoutMs = handshakeTimeoutMs,
        pairingWaitMs = pairingWaitMs,
    )

    /** Drive a full SAKE handshake through the captured listener, leaving the manager CONNECTED. */
    private fun completeHandshake(address: String = PUMP_ADDRESS) {
        listener.onPumpConnected(address)
        listener.onSakeSubscribed()
        val pump = SakeClient(SakeVectors.customClientKeyDb(), DeviceType.INSULIN_PUMP)
        listener.onSakeWrite(ByteArray(SAKE_FRAME_SIZE)) // pump wake-up write -> msg0
        listener.onSakeWrite(pump.handshake(notifications.last()))
        listener.onSakeWrite(pump.handshake(notifications.last()))
        listener.onSakeWrite(pump.handshake(notifications.last()))
    }

    @Test
    fun `initial state is disconnected with no fault`() {
        val manager = newManager()
        assertEquals(ConnectionState.DISCONNECTED, manager.connectionState.value)
        assertNull(manager.fault.value)
        assertNull(manager.sakeSession)
    }

    @Test
    fun `startSession unpaired advertises first-pair and enters connecting`() {
        val manager = newManager()
        manager.startSession()
        assertEquals(ConnectionState.CONNECTING, manager.connectionState.value)
        verify { peripheral.start(AdvertisingMode.FIRST_PAIR, any(), any()) }
    }

    @Test
    fun `startSession paired advertises reconnect`() {
        credentialStore.savePairing(PUMP_ADDRESS, "Mobile 000001")
        val manager = newManager()
        manager.startSession()
        verify { peripheral.start(AdvertisingMode.RECONNECT, any(), any()) }
    }

    @Test
    fun `pump connect stops advertising and clears fault`() {
        val manager = newManager()
        manager.startSession()
        listener.onPumpConnected(PUMP_ADDRESS)
        verify { peripheral.stopAdvertising() }
        assertEquals(ConnectionState.CONNECTING, manager.connectionState.value)
        assertNull(manager.fault.value)
    }

    @Test
    fun `sake subscribe transitions to authenticating`() {
        val manager = newManager()
        manager.startSession()
        listener.onPumpConnected(PUMP_ADDRESS)
        listener.onSakeSubscribed()
        assertEquals(ConnectionState.AUTHENTICATING, manager.connectionState.value)
    }

    @Test
    fun `successful handshake connects holds session and persists pairing`() {
        val manager = newManager()
        manager.startSession()
        completeHandshake()

        assertEquals(ConnectionState.CONNECTED, manager.connectionState.value)
        assertNull(manager.fault.value)
        assertTrue(manager.sakeSession?.isComplete == true)
        assertEquals(1, credentialStore.savePairingCount)
        assertEquals(PUMP_ADDRESS, credentialStore.getPairedAddress())
    }

    @Test
    fun `no notification emitted during a session exceeds the PDU cap`() {
        val manager = newManager()
        manager.startSession()
        completeHandshake()
        assertTrue(notifications.isNotEmpty())
        notifications.forEach { assertTrue("PDU ${it.size}B too large", it.size <= PduFramer.MAX_PDU_SIZE) }
    }

    @Test
    fun `disconnect after connect re-advertises in reconnect mode`() {
        val manager = newManager()
        manager.startSession()
        completeHandshake()

        listener.onPumpDisconnected(GATT_TERMINATE_PEER_USER)

        assertEquals(ConnectionState.RECONNECTING, manager.connectionState.value)
        assertNull(manager.sakeSession)
        verify { peripheral.advertise(AdvertisingMode.RECONNECT, any()) }
    }

    @Test
    fun `auth failure latches auth_failed and survives the following disconnect`() {
        val manager = newManager()
        manager.startSession()
        listener.onPumpConnected(PUMP_ADDRESS)
        listener.onSakeSubscribed()
        val pump = SakeClient(SakeVectors.customClientKeyDb(), DeviceType.INSULIN_PUMP)
        listener.onSakeWrite(ByteArray(SAKE_FRAME_SIZE))
        listener.onSakeWrite(pump.handshake(notifications.last()))
        listener.onSakeWrite(pump.handshake(notifications.last()))
        val msg5 = pump.handshake(notifications.last())
        listener.onSakeWrite(msg5.clone().also { it[0] = (it[0].toInt() xor 0x01).toByte() })

        assertEquals(ConnectionState.AUTH_FAILED, manager.connectionState.value)
        assertEquals(MedtronicConnectionFault.AUTH_FAILED, manager.fault.value)

        // The pump drops the link after rejecting us; AUTH_FAILED must not be overwritten or retried.
        listener.onPumpDisconnected(GATT_TERMINATE_PEER_USER)
        assertEquals(ConnectionState.AUTH_FAILED, manager.connectionState.value)
        verify(exactly = 0) { peripheral.advertise(any(), any()) }
    }

    @Test
    fun `handshake timeout reports auth_failed with timeout fault`() {
        val manager = newManager(handshakeTimeoutMs = 5_000L)
        manager.startSession()
        listener.onPumpConnected(PUMP_ADDRESS)
        listener.onSakeSubscribed()

        testScope.advanceTimeBy(5_001L)
        testScope.runCurrent()

        assertEquals(ConnectionState.AUTH_FAILED, manager.connectionState.value)
        assertEquals(MedtronicConnectionFault.HANDSHAKE_TIMEOUT, manager.fault.value)
    }

    @Test
    fun `first-pair single-peer wait surfaces bound-elsewhere fault`() {
        val manager = newManager(pairingWaitMs = 10_000L)
        manager.startSession()
        listener.onAdvertiseStarted(AdvertisingMode.FIRST_PAIR)

        testScope.advanceTimeBy(10_001L)
        testScope.runCurrent()

        assertEquals(MedtronicConnectionFault.BOUND_ELSEWHERE_SUSPECTED, manager.fault.value)
        assertEquals(ConnectionState.CONNECTING, manager.connectionState.value)
    }

    @Test
    fun `disconnect stops the peripheral and prevents reconnect`() {
        credentialStore.savePairing(PUMP_ADDRESS, "Mobile 000001")
        val manager = newManager()
        manager.startSession()

        manager.disconnect()

        assertEquals(ConnectionState.DISCONNECTED, manager.connectionState.value)
        verify { peripheral.stop() }
        // A late disconnect callback must not start a reconnect after the user disconnected.
        listener.onPumpDisconnected(GATT_TERMINATE_PEER_USER)
        assertEquals(ConnectionState.DISCONNECTED, manager.connectionState.value)
        verify(exactly = 0) { peripheral.advertise(any(), any()) }
    }

    @Test
    fun `unpair clears credentials and removes the bond`() {
        credentialStore.savePairing(PUMP_ADDRESS, "Mobile 000001")
        val manager = newManager()

        manager.unpair()

        assertNull(credentialStore.getPairedAddress())
        assertEquals(1, credentialStore.clearPairingCount)
        verify { peripheral.removeBond(PUMP_ADDRESS) }
    }

    @Test
    fun `advertise failure reports advertise_failed`() {
        val manager = newManager()
        manager.startSession()
        listener.onAdvertiseFailed(ADVERTISE_ERROR)

        assertEquals(ConnectionState.DISCONNECTED, manager.connectionState.value)
        assertEquals(MedtronicConnectionFault.ADVERTISE_FAILED, manager.fault.value)
    }

    @Test
    fun `unsupported peripheral reports unsupported fault and does not advertise`() {
        every { peripheral.isSupported() } returns false
        val manager = newManager()
        manager.startSession()

        assertEquals(MedtronicConnectionFault.PERIPHERAL_UNSUPPORTED, manager.fault.value)
        assertEquals(ConnectionState.DISCONNECTED, manager.connectionState.value)
        verify(exactly = 0) { peripheral.start(any(), any(), any()) }
    }

    @Test
    fun `scan advertises and emits the pump that connects`() = runTest {
        val manager = newManager(scope = TestScope(StandardTestDispatcher(testScheduler)))
        val received = mutableListOf<DiscoveredDevice>()
        val job = launch { manager.scan().collect { received.add(it) } }
        runCurrent()

        assertEquals(ConnectionState.SCANNING, manager.connectionState.value)
        verify { peripheral.start(AdvertisingMode.FIRST_PAIR, any(), any()) }

        listener.onPumpConnected(PUMP_ADDRESS)
        runCurrent()

        assertEquals(1, received.size)
        assertEquals(PUMP_ADDRESS, received[0].address)
        assertEquals(MedtronicBleConnectionManager.PLUGIN_ID, received[0].pluginId)
        job.cancel()
    }

    @Test
    fun `scan on an unsupported device completes with the unsupported fault`() = runTest {
        every { peripheral.isSupported() } returns false
        val manager = newManager(scope = TestScope(StandardTestDispatcher(testScheduler)))
        val received = mutableListOf<DiscoveredDevice>()

        manager.scan().collect { received.add(it) } // closes immediately

        assertTrue(received.isEmpty())
        assertEquals(MedtronicConnectionFault.PERIPHERAL_UNSUPPORTED, manager.fault.value)
        verify(exactly = 0) { peripheral.start(any(), any(), any()) }
    }

    private companion object {
        const val PUMP_ADDRESS = "AA:BB:CC:DD:EE:FF"
        const val SAKE_FRAME_SIZE = 20
        const val GATT_TERMINATE_PEER_USER = 0x13
        const val ADVERTISE_ERROR = 3
    }
}
