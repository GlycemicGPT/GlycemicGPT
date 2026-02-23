package com.glycemicgpt.mobile.data.local

import com.glycemicgpt.mobile.BuildConfig
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.time.Instant
import javax.inject.Inject
import javax.inject.Singleton

/**
 * In-memory circular buffer of recent BLE debug entries for the
 * in-app debug viewer. Stores the last [CAPACITY] entries.
 *
 * All mutating operations are no-ops in release builds (R8 will
 * eliminate the dead code since [BuildConfig.DEBUG] is a compile-time constant).
 */
@Singleton
class BleDebugStore @Inject constructor() {

    companion object {
        const val CAPACITY = 100
    }

    data class Entry(
        val timestamp: Instant,
        val direction: Direction,
        val opcode: Int,
        val opcodeName: String,
        val txId: Int,
        val cargoHex: String,
        val cargoSize: Int,
        val parsedValue: String? = null,
        val error: String? = null,
    )

    enum class Direction { TX, RX }

    private val buffer = ArrayDeque<Entry>(CAPACITY)
    private val _entries = MutableStateFlow<List<Entry>>(emptyList())
    val entries: StateFlow<List<Entry>> = _entries.asStateFlow()

    @Synchronized
    fun add(entry: Entry) {
        if (!BuildConfig.DEBUG) return
        if (buffer.size >= CAPACITY) {
            buffer.removeFirst()
        }
        buffer.addLast(entry)
        _entries.value = buffer.toList()
    }

    /**
     * Atomically update the most recent entry matching [opcode] and [direction]
     * with parse results. This modifies in-place rather than appending a duplicate.
     */
    @Synchronized
    fun updateLast(opcode: Int, direction: Direction, parsedValue: String? = null, error: String? = null) {
        if (!BuildConfig.DEBUG) return
        val idx = buffer.indexOfLast { it.opcode == opcode && it.direction == direction }
        if (idx < 0) return
        buffer[idx] = buffer[idx].copy(parsedValue = parsedValue, error = error)
        _entries.value = buffer.toList()
    }

    @Synchronized
    fun clear() {
        buffer.clear()
        _entries.value = emptyList()
    }
}
