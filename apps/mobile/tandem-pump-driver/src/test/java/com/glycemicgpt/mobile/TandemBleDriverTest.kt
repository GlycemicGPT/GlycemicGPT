package com.glycemicgpt.mobile

import com.glycemicgpt.mobile.ble.connection.BleConnectionManager
import com.glycemicgpt.mobile.ble.connection.TandemBleDriver
import com.glycemicgpt.mobile.ble.protocol.TandemProtocol
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.model.ConnectionState
import com.glycemicgpt.mobile.domain.pump.DebugLogger
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.time.Instant
import java.util.concurrent.TimeoutException

class TandemBleDriverTest {

    private val connectionStateFlow = MutableStateFlow(ConnectionState.DISCONNECTED)
    private val debugLogger = mockk<DebugLogger>(relaxed = true)
    private val connectionManager = mockk<BleConnectionManager>(relaxed = true) {
        every { connectionState } returns connectionStateFlow
    }
    private val driver = TandemBleDriver(connectionManager, debugLogger)

    @Test
    fun `initial connection state is disconnected`() = runTest {
        val state = driver.observeConnectionState().first()
        assertEquals(ConnectionState.DISCONNECTED, state)
    }

    @Test
    fun `connect delegates to connection manager`() = runTest {
        val result = driver.connect("AA:BB:CC:DD:EE:FF")
        assertTrue(result.isSuccess)
        verify { connectionManager.connect("AA:BB:CC:DD:EE:FF", null) }
    }

    @Test
    fun `disconnect delegates to connection manager`() = runTest {
        val result = driver.disconnect()
        assertTrue(result.isSuccess)
        verify { connectionManager.disconnect() }
    }

    @Test
    fun `observeConnectionState returns manager state`() = runTest {
        connectionStateFlow.value = ConnectionState.CONNECTED
        val state = driver.observeConnectionState().first()
        assertEquals(ConnectionState.CONNECTED, state)
    }

    // -- IoB read tests (opcode 108, 17-byte cargo) ----------------------------

    @Test
    fun `getIoB returns parsed reading on success`() = runTest {
        // 17-byte ControlIQIOBResponse: mudaliar=2500, time=3600, total=3000, swan=1500, iobType=1
        val buf = ByteBuffer.allocate(17).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(2500)  // mudaliarIOB (milliunits)
        buf.putInt(3600)  // timeRemainingSeconds
        buf.putInt(3000)  // mudaliarTotalIOB
        buf.putInt(1500)  // swan6hrIOB (milliunits)
        buf.put(1)        // iobType=SWAN_6HR -> use swan value
        coEvery {
            connectionManager.sendStatusRequest(TandemProtocol.OPCODE_CONTROL_IQ_IOB_REQ, any(), any())
        } returns buf.array()

        val result = driver.getIoB()
        assertTrue(result.isSuccess)
        assertEquals(1.5f, result.getOrThrow().iob, 0.001f)
    }

    @Test
    fun `getIoB returns failure on timeout`() = runTest {
        coEvery {
            connectionManager.sendStatusRequest(TandemProtocol.OPCODE_CONTROL_IQ_IOB_REQ, any(), any())
        } throws TimeoutException("timed out")

        val result = driver.getIoB()
        assertTrue(result.isFailure)
        assertTrue(result.exceptionOrNull() is TimeoutException)
    }

    @Test
    fun `getIoB returns failure when not connected`() = runTest {
        coEvery {
            connectionManager.sendStatusRequest(any(), any(), any())
        } throws IllegalStateException("Not connected to pump")

        val result = driver.getIoB()
        assertTrue(result.isFailure)
    }

    // -- Basal rate tests (opcode 40, 9-byte cargo) ----------------------------

    @Test
    fun `getBasalRate returns parsed reading on success`() = runTest {
        // 9-byte CurrentBasalStatusResponse: profileRate=800, currentRate=750, modified=1
        val buf = ByteBuffer.allocate(9).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(800)   // profileBasalRate (milliunits/hr)
        buf.putInt(750)   // currentBasalRate (milliunits/hr)
        buf.put(1)        // modified (1=automated/CIQ)
        coEvery {
            connectionManager.sendStatusRequest(TandemProtocol.OPCODE_CURRENT_BASAL_STATUS_REQ, any(), any())
        } returns buf.array()

        val result = driver.getBasalRate()
        assertTrue(result.isSuccess)
        assertEquals(0.75f, result.getOrThrow().rate, 0.001f)
        assertTrue(result.getOrThrow().isAutomated)
    }

    // -- Battery tests (V2 opcode 144, V1 opcode 52) ---------------------------

    @Test
    fun `getBatteryStatus returns V1 reading on success`() = runTest {
        // 2-byte V1 response: abc=27, ibc=85
        coEvery {
            connectionManager.sendStatusRequest(TandemProtocol.OPCODE_CURRENT_BATTERY_V1_REQ, any(), any())
        } returns byteArrayOf(27, 85.toByte())

        val result = driver.getBatteryStatus()
        assertTrue(result.isSuccess)
        assertEquals(85, result.getOrThrow().percentage)
        assertFalse(result.getOrThrow().isCharging) // V1 has no charging flag
    }

    @Test
    fun `getBatteryStatus falls back to V2 when V1 fails`() = runTest {
        // V1 fails (e.g., on Mobi pumps)
        coEvery {
            connectionManager.sendStatusRequest(TandemProtocol.OPCODE_CURRENT_BATTERY_V1_REQ, any(), any())
        } throws IllegalStateException("V1 not supported")
        // V2 succeeds: 11-byte response
        val v2Cargo = ByteArray(11)
        v2Cargo[0] = 99.toByte() // abc
        v2Cargo[1] = 72          // ibc = 72%
        v2Cargo[2] = 1           // charging
        coEvery {
            connectionManager.sendStatusRequest(TandemProtocol.OPCODE_CURRENT_BATTERY_V2_REQ, any(), any())
        } returns v2Cargo

        val result = driver.getBatteryStatus()
        assertTrue(result.isSuccess)
        assertEquals(72, result.getOrThrow().percentage)
        assertTrue(result.getOrThrow().isCharging)
    }

    // -- Reservoir tests (opcode 36, uint16 whole units) -----------------------

    @Test
    fun `getReservoirLevel returns parsed reading on success`() = runTest {
        // InsulinStatusResponse: uint16 LE whole units (NOT milliunits)
        val buf = ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN)
        buf.putShort(150.toShort()) // 150 units
        buf.put(0)                  // exact
        buf.put(35)                 // low threshold
        coEvery {
            connectionManager.sendStatusRequest(TandemProtocol.OPCODE_INSULIN_STATUS_REQ, any(), any())
        } returns buf.array()

        val result = driver.getReservoirLevel()
        assertTrue(result.isSuccess)
        assertEquals(150f, result.getOrThrow().unitsRemaining, 0.001f)
    }

    // -- Pump settings tests ---------------------------------------------------

    @Test
    fun `getPumpSettings returns parsed settings on success`() = runTest {
        val fw = "7.8.1".toByteArray()
        val serial = "SN123".toByteArray()
        val model = "X2".toByteArray()
        val buf = ByteBuffer.allocate(4 + fw.size + 4 + serial.size + 4 + model.size)
            .order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(fw.size).put(fw)
        buf.putInt(serial.size).put(serial)
        buf.putInt(model.size).put(model)

        coEvery {
            connectionManager.sendStatusRequest(TandemProtocol.OPCODE_PUMP_SETTINGS_REQ, any(), any())
        } returns buf.array()

        val result = driver.getPumpSettings()
        assertTrue(result.isSuccess)
        assertEquals("7.8.1", result.getOrThrow().firmwareVersion)
        assertEquals("SN123", result.getOrThrow().serialNumber)
    }

    // -- Bolus history tests (LastBolusStatus opcode 48) -------------------------

    @Test
    fun `getBolusHistory returns parsed events on success`() = runTest {
        // LastBolusStatusResponse: 17 bytes
        // bolusId=42, timestamp=recent, volume=3500 milliunits, status=3(COMPLETED),
        // source=0(GUI), type=1(STANDARD), extDuration=0
        val recentPumpTime = (Instant.now().epochSecond - 1199145600L - 600).toInt()
        val buf = ByteBuffer.allocate(17).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(42)            // bolusId
        buf.putInt(recentPumpTime) // timestamp (Tandem epoch)
        buf.putInt(3500)          // deliveredVolume (milliunits = 3.5 units)
        buf.put(3)                // bolusStatusId = COMPLETED
        buf.put(0)                // bolusSourceId = GUI
        buf.put(1)                // bolusTypeBitmask = STANDARD
        buf.putShort(0)           // extendedBolusDuration = 0

        coEvery {
            connectionManager.sendStatusRequest(TandemProtocol.OPCODE_LAST_BOLUS_STATUS_REQ, any(), any())
        } returns buf.array()

        val since = Instant.now().minusSeconds(3600)
        val result = driver.getBolusHistory(since)
        assertTrue(result.isSuccess)
        assertEquals(1, result.getOrThrow().size)
        assertEquals(3.5f, result.getOrThrow()[0].units, 0.001f)
    }

    // -- CGM status tests (EGV opcode 34 + HomeScreenMirror opcode 56) ---------

    @Test
    fun `getCgmStatus merges EGV and HomeScreenMirror data`() = runTest {
        // EGV response: 8 bytes - timestamp, glucose=120, status=1 (VALID), trendRate=0
        val egvBuf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
        egvBuf.putInt(471039176) // Tandem epoch timestamp
        egvBuf.putShort(120)     // 120 mg/dL
        egvBuf.put(1)            // VALID
        egvBuf.put(0)            // trendRate
        coEvery {
            connectionManager.sendStatusRequest(TandemProtocol.OPCODE_CGM_EGV_REQ, any(), any())
        } returns egvBuf.array()

        // HomeScreenMirror response: 9 bytes - trendIconId=4 (FLAT), rest zeros
        val mirrorCargo = ByteArray(9)
        mirrorCargo[0] = 4 // FLAT trend
        coEvery {
            connectionManager.sendStatusRequest(TandemProtocol.OPCODE_HOME_SCREEN_MIRROR_REQ, any(), any())
        } returns mirrorCargo

        val result = driver.getCgmStatus()
        assertTrue(result.isSuccess)
        assertEquals(120, result.getOrThrow().glucoseMgDl)
        assertEquals(CgmTrend.FLAT, result.getOrThrow().trendArrow)
    }

    @Test
    fun `getCgmStatus returns UNKNOWN trend when mirror fails`() = runTest {
        val egvBuf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
        egvBuf.putInt(471039176)
        egvBuf.putShort(180)
        egvBuf.put(1) // VALID
        egvBuf.put(0)
        coEvery {
            connectionManager.sendStatusRequest(TandemProtocol.OPCODE_CGM_EGV_REQ, any(), any())
        } returns egvBuf.array()

        // HomeScreenMirror fails
        coEvery {
            connectionManager.sendStatusRequest(TandemProtocol.OPCODE_HOME_SCREEN_MIRROR_REQ, any(), any())
        } throws IllegalStateException("timeout")

        val result = driver.getCgmStatus()
        assertTrue(result.isSuccess)
        assertEquals(180, result.getOrThrow().glucoseMgDl)
        assertEquals(CgmTrend.UNKNOWN, result.getOrThrow().trendArrow)
    }

    // -- Opcode verification ---------------------------------------------------

    @Test
    fun `each read method uses correct opcode`() = runTest {
        coEvery { connectionManager.sendStatusRequest(any(), any(), any()) } throws
            IllegalStateException("not connected")

        driver.getIoB()
        driver.getBasalRate()
        driver.getBatteryStatus()
        driver.getReservoirLevel()
        driver.getPumpSettings()
        driver.getBolusHistory(Instant.now())
        driver.getCgmStatus()

        coVerify { connectionManager.sendStatusRequest(108, any(), any()) } // IoB
        coVerify { connectionManager.sendStatusRequest(40, any(), any()) }  // Basal
        coVerify { connectionManager.sendStatusRequest(52, any(), any()) }  // Battery V1 (tried first)
        coVerify { connectionManager.sendStatusRequest(36, any(), any()) }  // Insulin/Reservoir
        coVerify { connectionManager.sendStatusRequest(82, any(), any()) }  // Pump Settings
        coVerify { connectionManager.sendStatusRequest(48, any(), any()) }  // Last Bolus Status
        coVerify { connectionManager.sendStatusRequest(34, any(), any()) }  // CGM EGV
        // HomeScreenMirror (56) is only called if EGV succeeds -- verified in getCgmStatus tests above
    }
}
