package com.glycemicgpt.mobile.data.local

import com.glycemicgpt.mobile.BuildConfig
import com.glycemicgpt.mobile.domain.pump.DebugLogger
import java.time.Instant
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Adapter that bridges the [DebugLogger] interface (used by the tandem-pump-driver
 * module) to the app-level [BleDebugStore] (which depends on BuildConfig.DEBUG).
 *
 * Both methods short-circuit in release builds to avoid allocating [BleDebugStore.Entry]
 * objects and [Instant.now] calls on the BLE callback thread when the underlying store
 * will discard them anyway.
 */
@Singleton
class BleDebugStoreAdapter @Inject constructor(
    private val store: BleDebugStore,
) : DebugLogger {

    /** Visible for testing; defaults to [BuildConfig.DEBUG]. */
    internal var debugEnabled: Boolean = BuildConfig.DEBUG

    override fun logPacket(
        direction: DebugLogger.Direction,
        opcode: Int,
        opcodeName: String,
        txId: Int,
        cargoHex: String,
        cargoSize: Int,
        parsedValue: String?,
        error: String?,
    ) {
        if (!debugEnabled) return
        store.add(
            BleDebugStore.Entry(
                timestamp = Instant.now(),
                direction = direction.toStoreDirection(),
                opcode = opcode,
                opcodeName = opcodeName,
                txId = txId,
                cargoHex = cargoHex,
                cargoSize = cargoSize,
                parsedValue = parsedValue,
                error = error,
            ),
        )
    }

    override fun updateLastPacket(
        opcode: Int,
        direction: DebugLogger.Direction,
        parsedValue: String?,
        error: String?,
    ) {
        if (!debugEnabled) return
        store.updateLast(opcode, direction.toStoreDirection(), parsedValue, error)
    }

    private fun DebugLogger.Direction.toStoreDirection(): BleDebugStore.Direction =
        when (this) {
            DebugLogger.Direction.TX -> BleDebugStore.Direction.TX
            DebugLogger.Direction.RX -> BleDebugStore.Direction.RX
        }
}
