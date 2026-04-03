package com.glycemicgpt.mobile.data.local

import com.glycemicgpt.mobile.domain.pump.DebugLogger
import io.mockk.mockk
import io.mockk.verify
import org.junit.Test

class BleDebugStoreAdapterTest {

    private val store = mockk<BleDebugStore>(relaxed = true)
    private val adapter = BleDebugStoreAdapter(store)

    @Test
    fun `logPacket maps TX direction correctly`() {
        adapter.logPacket(
            direction = DebugLogger.Direction.TX,
            opcode = 42,
            opcodeName = "TestOp",
            txId = 1,
            cargoHex = "ab cd",
            cargoSize = 2,
            parsedValue = "parsed",
            error = null,
        )
        verify {
            store.add(match { entry ->
                entry.direction == BleDebugStore.Direction.TX &&
                    entry.opcode == 42 &&
                    entry.opcodeName == "TestOp" &&
                    entry.txId == 1 &&
                    entry.cargoHex == "ab cd" &&
                    entry.cargoSize == 2 &&
                    entry.parsedValue == "parsed" &&
                    entry.error == null &&
                    entry.timestamp.toEpochMilli() > 0
            })
        }
    }

    @Test
    fun `logPacket maps RX direction correctly`() {
        adapter.logPacket(
            direction = DebugLogger.Direction.RX,
            opcode = 99,
            opcodeName = "RxOp",
            txId = 7,
            cargoHex = "ff",
            cargoSize = 1,
            parsedValue = null,
            error = "oops",
        )
        verify {
            store.add(match { entry ->
                entry.direction == BleDebugStore.Direction.RX &&
                    entry.opcode == 99 &&
                    entry.opcodeName == "RxOp" &&
                    entry.txId == 7 &&
                    entry.cargoHex == "ff" &&
                    entry.cargoSize == 1 &&
                    entry.parsedValue == null &&
                    entry.error == "oops" &&
                    entry.timestamp.toEpochMilli() > 0
            })
        }
    }

    @Test
    fun `updateLastPacket delegates with correct direction mapping`() {
        adapter.updateLastPacket(
            opcode = 42,
            direction = DebugLogger.Direction.TX,
            parsedValue = "updated",
            error = null,
        )
        verify {
            store.updateLast(42, BleDebugStore.Direction.TX, "updated", null)
        }
    }

    @Test
    fun `updateLastPacket maps RX direction`() {
        adapter.updateLastPacket(
            opcode = 10,
            direction = DebugLogger.Direction.RX,
            parsedValue = null,
            error = "fail",
        )
        verify {
            store.updateLast(10, BleDebugStore.Direction.RX, null, "fail")
        }
    }

    // -- Release-build no-op tests ------------------------------------------------

    @Test
    fun `logPacket is no-op when debug disabled`() {
        adapter.debugEnabled = false
        adapter.logPacket(
            direction = DebugLogger.Direction.TX,
            opcode = 42,
            opcodeName = "TestOp",
            txId = 1,
            cargoHex = "ab cd",
            cargoSize = 2,
            parsedValue = "parsed",
            error = null,
        )
        verify(exactly = 0) { store.add(any()) }
    }

    @Test
    fun `updateLastPacket is no-op when debug disabled`() {
        adapter.debugEnabled = false
        adapter.updateLastPacket(
            opcode = 42,
            direction = DebugLogger.Direction.TX,
            parsedValue = "updated",
            error = null,
        )
        verify(exactly = 0) { store.updateLast(any(), any(), any(), any()) }
    }
}
