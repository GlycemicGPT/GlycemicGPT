/*
 * Tests for SakeHandshakeDriver: the worker-thread handshake driving on top of the vendored JavaSake
 * (proven byte-for-byte by org.openminimed.sake.* and exercised through the wrapper by
 * MedtronicSakeSessionTest). Here the pump side is simulated with SakeClient + the matched synthetic
 * key-DB pair, so a full six-stage handshake runs end-to-end without any Android BLE stack.
 */
package com.glycemicgpt.mobile.ble.connection

import com.glycemicgpt.mobile.ble.protocol.PduFramer
import com.glycemicgpt.mobile.ble.sake.MedtronicSakeSession
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.openminimed.sake.DeviceType
import org.openminimed.sake.KeyDatabase
import org.openminimed.sake.MacFailureException
import org.openminimed.sake.SakeClient
import org.openminimed.sake.Session

class SakeHandshakeDriverTest {

    private val notifications = mutableListOf<ByteArray>()
    private val worker = DirectSerialWorker()
    private var authenticatedSession: MedtronicSakeSession? = null
    private var failure: Throwable? = null
    private var authCount = 0
    private var failCount = 0

    private fun newDriver(keyDb: KeyDatabase) = SakeHandshakeDriver(
        worker = worker,
        sessionFactory = { MedtronicSakeSession(keyDb) },
        notifySink = { notifications.add(it.copyOf()); true },
        listener = object : SakeHandshakeDriver.HandshakeListener {
            override fun onAuthenticated(session: MedtronicSakeSession) {
                authenticatedSession = session
                authCount++
            }

            override fun onAuthFailed(cause: Throwable?) {
                failure = cause
                failCount++
            }
        },
    )

    private fun newPump() = SakeClient(SakeVectors.customClientKeyDb(), DeviceType.INSULIN_PUMP)

    @Test
    fun `wake-up notification on subscribe is 20 zero bytes`() {
        newDriver(SakeVectors.pumpKeyDb()).onSubscribed()
        assertEquals(1, notifications.size)
        assertArrayEquals(ByteArray(Session.MESSAGE_SIZE), notifications[0])
    }

    @Test
    fun `full handshake drives to completion and holds the session`() {
        val driver = newDriver(SakeVectors.customServerKeyDb())
        val pump = newPump()

        driver.onSubscribed()
        driver.onPumpWrite(ByteArray(Session.MESSAGE_SIZE)) // pump's wake-up write -> msg0
        val msg1 = pump.handshake(notifications.last())
        driver.onPumpWrite(msg1) // -> msg2
        val msg3 = pump.handshake(notifications.last())
        driver.onPumpWrite(msg3) // -> msg4
        val msg5 = pump.handshake(notifications.last())
        driver.onPumpWrite(msg5) // -> completes, no further notification

        assertNotNull(authenticatedSession)
        assertTrue(authenticatedSession!!.isComplete)
        assertEquals(1, authCount)
        assertEquals(0, failCount)
        // Wake-up + msg0 + msg2 + msg4 = 4 notifications; the completing write produces none.
        assertEquals(4, notifications.size)
    }

    @Test
    fun `no notification exceeds the 20-byte PDU cap`() {
        // B2 only ever emits 20-byte SAKE frames, so this proves the driver never exceeds the cap on
        // the handshake path (AC4). The driver routes every notification through PduFramer.fragment,
        // whose fragmentation of larger (Milestone C reader) payloads is covered by PduFramerTest.
        val driver = newDriver(SakeVectors.customServerKeyDb())
        val pump = newPump()

        driver.onSubscribed()
        driver.onPumpWrite(ByteArray(Session.MESSAGE_SIZE))
        driver.onPumpWrite(pump.handshake(notifications.last()))
        driver.onPumpWrite(pump.handshake(notifications.last()))
        driver.onPumpWrite(pump.handshake(notifications.last()))

        assertTrue(notifications.isNotEmpty())
        notifications.forEach { assertTrue("PDU ${it.size}B exceeds cap", it.size <= PduFramer.MAX_PDU_SIZE) }
    }

    @Test
    fun `tampered final permit fails authentication`() {
        val driver = newDriver(SakeVectors.customServerKeyDb())
        val pump = newPump()

        driver.onSubscribed()
        driver.onPumpWrite(ByteArray(Session.MESSAGE_SIZE))
        driver.onPumpWrite(pump.handshake(notifications.last()))
        driver.onPumpWrite(pump.handshake(notifications.last()))
        val msg5 = pump.handshake(notifications.last())
        val tampered = msg5.clone().also { it[0] = (it[0].toInt() xor 0x01).toByte() }
        driver.onPumpWrite(tampered)

        assertNull(authenticatedSession)
        assertEquals(1, failCount)
        assertTrue(failure is MacFailureException)

        // Further pump writes on the now-corrupted session must not re-fire onAuthFailed.
        driver.onPumpWrite(ByteArray(Session.MESSAGE_SIZE))
        driver.onPumpWrite(ByteArray(Session.MESSAGE_SIZE))
        assertEquals(1, failCount)
    }

    @Test
    fun `writes after completion are ignored`() {
        val driver = newDriver(SakeVectors.customServerKeyDb())
        val pump = newPump()

        driver.onSubscribed()
        driver.onPumpWrite(ByteArray(Session.MESSAGE_SIZE))
        driver.onPumpWrite(pump.handshake(notifications.last()))
        driver.onPumpWrite(pump.handshake(notifications.last()))
        driver.onPumpWrite(pump.handshake(notifications.last()))
        val countAfterComplete = notifications.size

        driver.onPumpWrite(ByteArray(Session.MESSAGE_SIZE))

        assertEquals(1, authCount)
        assertEquals(0, failCount)
        assertEquals(countAfterComplete, notifications.size)
    }

    @Test
    fun `resubscribe after unsubscribe restarts the handshake cleanly`() {
        val driver = newDriver(SakeVectors.customServerKeyDb())

        // Begin a handshake, then the pump drops its subscription mid-flight.
        driver.onSubscribed()
        driver.onPumpWrite(ByteArray(Session.MESSAGE_SIZE)) // advances past stage 0
        driver.onUnsubscribed()
        notifications.clear()

        // A fresh subscribe re-emits the wake-up and a brand-new handshake completes.
        driver.onSubscribed()
        assertArrayEquals(ByteArray(Session.MESSAGE_SIZE), notifications.last())
        val pump = newPump()
        driver.onPumpWrite(ByteArray(Session.MESSAGE_SIZE))
        driver.onPumpWrite(pump.handshake(notifications.last()))
        driver.onPumpWrite(pump.handshake(notifications.last()))
        driver.onPumpWrite(pump.handshake(notifications.last()))

        assertNotNull(authenticatedSession)
        assertTrue(authenticatedSession!!.isComplete)
        assertEquals(1, authCount)
    }
}
