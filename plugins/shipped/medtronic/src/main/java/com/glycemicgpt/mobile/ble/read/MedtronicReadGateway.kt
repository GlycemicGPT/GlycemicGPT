/*
 * GlycemicGPT code (GPL-3.0). Capability-facing read bundle for the Medtronic MiniMed 700-series
 * read-only driver.
 *
 * This is the Medtronic analog of Tandem's `TandemBleDriver`: a single seam the capability delegates
 * (MedtronicGlucoseSource / MedtronicInsulinSource / MedtronicPumpStatus) forward to, so the delegates
 * stay thin. It owns four cross-cutting concerns the individual C1/C2 readers deliberately left to
 * their caller (see MedtronicSessionReader's timeout contract):
 *   1. resolving the live SAKE session + the GATT-client transport, failing cleanly when not connected;
 *   2. bounding every read with a per-operation timeout (the readers carry no timers);
 *   3. serializing every read so no two exchanges overlap on the single one-exchange-at-a-time link
 *      (the polling orchestrator drives the fast/medium/slow tiers as independent coroutines, so this
 *      seam is where they coalesce into single-flight -- see [readMutex]);
 *   4. routing caught failures through Timber so they are observable in the glycemicgpt-mobile Sentry
 *      project once this runs in :app (Story AC7).
 *
 * It adds no parsing of its own -- the readers (CgmReader / IddStatusReader / HistoryReader /
 * DeviceInfoReader / BatteryReader) own that. READ-ONLY: only report/get-class reads are issued.
 *
 * **Transport seam.** The on-device `AndroidMedtronicGattLink` (a `BluetoothGatt` client to the
 * connected pump's CGM / IDD / Device-Info GATT server) implements [MedtronicGattLink] and is supplied
 * by the DI module's [linkProvider], which returns the link while a pump is `CONNECTED` and `null`
 * otherwise -- so reads report "not connected" rather than fabricate data when no pump is authenticated.
 * The link resolves the shared SIG `0x2A52` [MedtronicProtocol.RACP_UUID] under the CGM service for
 * [getCgmReading] and under the IDD service for [getHistoryLogs] (the readers reuse the same
 * characteristic UUID across both services). The link is strictly one-exchange-at-a-time; this gateway
 * owns the cross-exchange serialization (see [readMutex]).
 */
package com.glycemicgpt.mobile.ble.read

import com.glycemicgpt.mobile.ble.sake.MedtronicSakeSession
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.BatteryStatus
import com.glycemicgpt.mobile.domain.model.CgmReading
import com.glycemicgpt.mobile.domain.model.HistoryLogRecord
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.model.ReservoirReading
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.runInterruptible
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlin.coroutines.resume
import timber.log.Timber

/**
 * Bundles the Medtronic read layer behind suspend `Result<T>` calls for the capability delegates.
 *
 * @param sessionProvider supplies the live post-handshake session (the connection manager's
 *     `sakeSession`), or `null` when no pump is authenticated.
 * @param linkProvider supplies the GATT-client transport to the connected pump, or `null` when no pump
 *     is connected (see the class header).
 * @param ioDispatcher dispatcher for the blocking SIG reads (Device Info / Battery).
 * @param operationTimeoutMs hard upper bound on every read; expiry surfaces as a failed [Result].
 */
class MedtronicReadGateway(
    private val sessionProvider: () -> MedtronicSakeSession?,
    private val linkProvider: () -> MedtronicGattLink?,
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
    private val operationTimeoutMs: Long = DEFAULT_OPERATION_TIMEOUT_MS,
) {

    /**
     * Single-flight guard. The Medtronic link is strictly one-exchange-at-a-time: a read is a stateful
     * subscribe -> control-point write -> await-indication -> unsubscribe choreography on characteristics
     * the CGM and IDD services *share* (the SIG `0x2A52` RACP), with no transaction id to demultiplex
     * overlapping exchanges. The polling orchestrator runs the fast/medium/slow tiers as independent
     * coroutines, so two reads can be issued concurrently; this mutex serializes them into single-flight
     * so a slow exchange never interleaves with -- or stacks on top of -- the next one on the wire. The
     * lock is held for the whole exchange (including the per-operation timeout), so a queued read waits
     * its turn rather than spending its timeout budget racing for the link. The mutex is fair (FIFO), so
     * a waiting keep-alive read is admitted as soon as the in-flight exchange releases the link. Keeping
     * each exchange short enough to protect the pump's idle-timeout budget is the orchestrator's job (it
     * releases the link between history-backfill batches); this seam only guarantees non-overlap.
     */
    private val readMutex = Mutex()

    /** Latest sensor glucose (CGM RACP "report last record"). */
    suspend fun getCgmReading(): Result<CgmReading> =
        sessionRead("CGM") { link, session, onResult ->
            CgmReader(link, session).readLatest(onResult)
        }

    /** Insulin on board (IDD SRCP). PROVISIONAL until live-validated (the reader logs the marker). */
    suspend fun getIoB(): Result<IoBReading> =
        sessionRead("IOB") { link, session, onResult ->
            IddStatusReader(link, session).readIoB(onResult)
        }

    /** Active basal rate currently delivered, with closed-loop (SmartGuard) detection. */
    suspend fun getBasalRate(): Result<BasalReading> =
        sessionRead("basal") { link, session, onResult ->
            IddStatusReader(link, session).readActiveBasalRate(onResult)
        }

    /** Reservoir units remaining. */
    suspend fun getReservoirLevel(): Result<ReservoirReading> =
        sessionRead("reservoir") { link, session, onResult ->
            IddStatusReader(link, session).readReservoir(onResult)
        }

    /** Incremental history fetch: every record newer than [sinceSequence] (raw, preserved for dedup). */
    suspend fun getHistoryLogs(sinceSequence: Int): Result<List<HistoryLogRecord>> =
        sessionRead("history") { link, session, onResult ->
            HistoryReader(link, session).readSinceSequence(sinceSequence, onResult)
        }

    /** Battery percentage (plain SIG Battery Level read; no session required). */
    suspend fun getBatteryStatus(): Result<BatteryStatus> =
        blockingRead("battery") { link -> BatteryReader(link).read() }

    /** Device Information strings (model/serial/firmware/...); plain SIG reads, no session required. */
    suspend fun getDeviceInfo(): Result<MedtronicDeviceInfo> =
        blockingRead("device-info") { link -> DeviceInfoReader(link).read() }

    // -- Internals ----------------------------------------------------------

    /**
     * Run a callback-style reader that needs both the live session and the transport, bridged to a
     * suspend `Result<T>` under [operationTimeoutMs]. The readers invoke [onResult] exactly once on the
     * link's single delivery thread; the timeout is the caller-side bound their timeout contract
     * requires.
     *
     * **Cancellation/cleanup contract.** On a timeout this coroutine is cancelled while the reader may
     * still hold notification subscriptions on the link (the reader only unsubscribes when the pump
     * responds). The gateway cannot drop them here -- it does not know which characteristics the reader
     * subscribed. The on-device `AndroidMedtronicGattLink` satisfies this: a subscription watchdog
     * releases all outstanding subscriptions when an operation can no longer complete, so a timed-out
     * read leaves no dangling notifications that would desync the next exchange.
     */
    private suspend fun <T> sessionRead(
        op: String,
        start: (MedtronicGattLink, MedtronicSakeSession, (Result<T>) -> Unit) -> Unit,
    ): Result<T> {
        // Resolve the transport before queuing on [readMutex]: when no pump is connected this fails fast
        // (a clean "not connected" Result) instead of blocking behind any in-flight exchange.
        val link = linkProvider() ?: return notConnected(op, "transport unavailable")
        val session = sessionProvider() ?: return notConnected(op, "no authenticated session")
        // Hold the single-flight lock for the entire exchange so no other read touches the shared link
        // until this one's await-indication completes (or its timeout tears it down).
        return readMutex.withLock {
            withOperationTimeout(op) {
                // The readers issue blocking GATT read/write before registering their callback, so offload
                // to [ioDispatcher] (as [blockingRead] does); the callback resume is dispatcher-agnostic.
                withContext(ioDispatcher) {
                    suspendCancellableCoroutine { cont ->
                        start(link, session) { result -> if (cont.isActive) cont.resume(result) }
                    }
                }
            }
        }
    }

    /**
     * Run a synchronous (blocking) SIG reader off the caller thread, bounded by the operation timeout.
     *
     * Uses [runInterruptible] rather than plain [withContext]: a blocking GATT read is not a suspension
     * point, so `withTimeout` could not cancel it -- structured concurrency would wait for it to return
     * on its own. [runInterruptible] turns the operation timeout's cancellation into a thread interrupt,
     * so an interruptible blocking read (e.g. one parked on a latch / interruptible I/O) aborts at the
     * deadline. A read that ignores interruption still cannot be force-unwound here; the on-device
     * `AndroidMedtronicGattLink` therefore also enforces its own per-operation timeout, as the
     * [MedtronicGattLink] contract requires.
     */
    private suspend fun <T> blockingRead(op: String, read: (MedtronicGattLink) -> T): Result<T> {
        val link = linkProvider() ?: return notConnected(op, "transport unavailable")
        // Single-flight: a SIG battery/device-info read shares the same one-op-at-a-time link as the
        // session reads, so it queues behind any in-flight exchange rather than racing it.
        return readMutex.withLock {
            withOperationTimeout(op) {
                runInterruptible(ioDispatcher) {
                    @Suppress("TooGenericExceptionCaught")
                    try {
                        Result.success(read(link))
                    } catch (e: InterruptedException) {
                        // A timeout interrupt: rethrow so it surfaces as cancellation and the operation
                        // timeout reports it, rather than being swallowed into a Result.failure.
                        throw e
                    } catch (e: Exception) {
                        Result.failure(e)
                    }
                }
            }
        }
    }

    private suspend fun <T> withOperationTimeout(op: String, block: suspend () -> Result<T>): Result<T> =
        try {
            withTimeout(operationTimeoutMs) { block() }
                .onFailure { e ->
                    // WARN is forwarded to the glycemicgpt-mobile Sentry project, so it must NOT carry
                    // the exception message/stacktrace: reader failures embed health values (e.g.
                    // "SG 142 mg/dL outside ...", IOB/basal/reservoir) and raw pump bytes. Log only the
                    // operation + exception type at WARN; keep the full detail at DEBUG (local logcat).
                    Timber.w("Medtronic %s read failed: %s", op, e.javaClass.simpleName)
                    Timber.d(e, "Medtronic %s read failure detail", op)
                }
        } catch (e: TimeoutCancellationException) {
            // No PHI in a timeout, but keep the same WARN discipline (message only, throwable at DEBUG).
            Timber.w("Medtronic %s read timed out after %d ms", op, operationTimeoutMs)
            Timber.d(e, "Medtronic %s read timeout detail", op)
            Result.failure(MedtronicReadException("Medtronic $op read timed out after $operationTimeoutMs ms", e))
        }

    private fun <T> notConnected(op: String, reason: String): Result<T> {
        // Expected whenever no pump is connected; debug (not warn) so a poll that fires between sessions
        // never reads as a Sentry-worthy error.
        Timber.d("Medtronic %s read skipped: %s", op, reason)
        return Result.failure(MedtronicReadException("Medtronic $op read skipped: pump not connected ($reason)"))
    }

    companion object {
        /**
         * Per-operation timeout. A single read is a few BLE round trips of 20-byte PDUs; history fetches
         * page more but each record still arrives promptly. 30s matches the handshake timeout and the
         * 30s connect timeout the [com.glycemicgpt.mobile.domain.plugin.DevicePlugin] contract documents.
         */
        const val DEFAULT_OPERATION_TIMEOUT_MS = 30_000L
    }
}
