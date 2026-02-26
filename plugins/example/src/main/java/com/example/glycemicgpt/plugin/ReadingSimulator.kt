package com.example.glycemicgpt.plugin

import com.glycemicgpt.mobile.domain.model.BgmReading
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.isActive
import java.time.Instant
import java.util.Collections
import kotlin.math.PI
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.random.Random

/**
 * Generates simulated fingerstick blood glucose readings for the demo plugin.
 *
 * The simulator produces realistic glucose values using a sine-wave pattern
 * that cycles between 80 and 180 mg/dL with some randomness added. This
 * mimics the postprandial (after-meal) glucose curve a real BGM user would see.
 *
 * ## How it works
 *
 * - Base pattern: `130 + 50 * sin(phase)` gives values in the 80-180 range
 * - Random jitter of +/-10 mg/dL adds realism
 * - Phase advances on each reading, completing a full cycle every 12 readings
 * - Safety limits are checked reactively: the current value of the StateFlow
 *   is read on each iteration, so backend limit changes take effect immediately
 *
 * ## Usage
 *
 * ```kotlin
 * val simulator = ReadingSimulator()
 * simulator.start(intervalSeconds = 30, safetyLimits = limitsFlow)
 *     .collect { reading -> /* process BgmReading */ }
 * ```
 *
 * The Flow completes when the collecting coroutine is cancelled (e.g., on
 * plugin deactivation).
 */
class ReadingSimulator {

    /** Thread-safe RNG (Random.Default is a shared singleton but is thread-safe). */
    private val rng = Random.Default

    /** Tracks the sine-wave phase across readings. */
    private var phase = 0.0

    /** The most recent emitted reading, or null if none yet. */
    @Volatile
    var latestReading: BgmReading? = null
        private set

    /**
     * Thread-safe history of the last [MAX_HISTORY] readings for sparkline display.
     * Uses a synchronized list because writes happen on the simulator coroutine
     * and reads happen from the dashboard card flow (potentially different dispatchers).
     */
    private val _history: MutableList<Float> = Collections.synchronizedList(mutableListOf())
    val history: List<Float> get() = synchronized(_history) { _history.toList() }

    /** Thread-safe timestamped reading history for the detail screen. */
    private val _recentReadings: MutableList<Pair<Instant, Float>> =
        Collections.synchronizedList(mutableListOf())
    val recentReadings: List<Pair<Instant, Float>>
        get() = synchronized(_recentReadings) { _recentReadings.toList() }

    /**
     * Produces a [Flow] of simulated [BgmReading] values at the given interval.
     *
     * @param intervalSeconds Seconds between readings (configurable via plugin settings).
     * @param safetyLimits Reactive safety limits StateFlow; current value is read each
     *   iteration so backend changes take effect immediately.
     * @return A cold Flow that emits readings until the coroutine is cancelled.
     *
     * **Note:** Only one collector should be active per ReadingSimulator instance.
     * Multiple concurrent collectors would race on shared mutable state (phase, history).
     * The platform ensures this by managing a single activation scope per plugin.
     */
    fun start(intervalSeconds: Long, safetyLimits: StateFlow<SafetyLimits>): Flow<BgmReading> = flow {
        require(intervalSeconds > 0) { "intervalSeconds must be positive, was $intervalSeconds" }
        while (currentCoroutineContext().isActive) {
            val raw = generateRawValue()
            // Read the CURRENT safety limits on each iteration (reactive).
            // Real plugins MUST do this -- safety limits can change at any time
            // when the backend pushes new values.
            val limits = safetyLimits.value
            if (raw < limits.minGlucoseMgDl || raw > limits.maxGlucoseMgDl) {
                println(
                    "DemoGlucometer: dropping out-of-range reading $raw mg/dL " +
                        "(limits: ${limits.minGlucoseMgDl}-${limits.maxGlucoseMgDl})",
                )
            } else {
                val reading = BgmReading(
                    glucoseMgDl = raw,
                    timestamp = Instant.now(),
                    meterName = "Demo Glucometer",
                )
                latestReading = reading
                recordHistory(raw.toFloat())
                emit(reading)
            }
            delay(intervalSeconds * 1000L)
        }
    }

    /**
     * Generates a single raw glucose value using sine-wave + jitter.
     * Values are clamped to BgmReading's valid range (20-500).
     */
    private fun generateRawValue(): Int {
        // Sine wave: center=130, amplitude=50 -> range 80-180
        val base = 130.0 + 50.0 * sin(phase)
        // Random jitter: +/- 10 mg/dL (using per-instance RNG, not Math.random())
        val jitter = rng.nextDouble(-10.0, 10.0)
        // Advance phase (full cycle every 12 readings)
        phase += (2.0 * PI / 12.0)
        return (base + jitter).roundToInt().coerceIn(20, 500)
    }

    /**
     * Adds a manual reading to history (for detail screen manual entry).
     * Validates that the value is within BgmReading's valid range (20-500 mg/dL).
     */
    fun addManualReading(glucoseMgDl: Float) {
        require(glucoseMgDl in 20f..500f) {
            "Manual reading must be between 20 and 500 mg/dL, was $glucoseMgDl"
        }
        recordHistory(glucoseMgDl)
    }

    private fun recordHistory(value: Float) {
        val now = Instant.now()
        synchronized(_history) {
            _history.add(value)
            if (_history.size > MAX_HISTORY) {
                _history.removeAt(0)
            }
        }
        synchronized(_recentReadings) {
            _recentReadings.add(now to value)
            if (_recentReadings.size > MAX_HISTORY) {
                _recentReadings.removeAt(0)
            }
        }
    }

    companion object {
        /** Number of readings to keep for sparkline display. */
        const val MAX_HISTORY = 12
    }
}
