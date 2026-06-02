/*
 * GlycemicGPT code (GPL-3.0). Capability-facing read bundle for the Medtronic MiniMed 700-series
 * read-only driver.
 *
 * This is the Medtronic analog of Tandem's `TandemBleDriver`: a single seam the capability delegates
 * (MedtronicGlucoseSource / MedtronicInsulinSource / MedtronicPumpStatus) forward to, so the delegates
 * stay thin. It owns three cross-cutting concerns the individual C1/C2 readers deliberately left to
 * their caller (see MedtronicSessionReader's timeout contract):
 *   1. resolving the live SAKE session + the GATT-client transport, failing cleanly when not connected;
 *   2. bounding every read with a per-operation timeout (the readers carry no timers);
 *   3. routing caught failures through Timber so they are observable in the glycemicgpt-mobile Sentry
 *      project once this runs in :app (Story AC7).
 *
 * It adds no parsing of its own -- the readers (CgmReader / IddStatusReader / HistoryReader /
 * DeviceInfoReader / BatteryReader) own that. READ-ONLY: only report/get-class reads are issued.
 *
 * **Transport seam (Milestone D).** The on-device [MedtronicGattLink] (a `BluetoothGatt` client to the
 * connected pump's CGM / IDD / Device-Info GATT server) is wired with the polling/orchestration slice
 * in Milestone D; [linkProvider] returns `null` until then, so reads report "not connected" rather
 * than fabricate data. Pairing, the SAKE handshake and connection state already work end-to-end
 * (Milestone B2), so the plugin is fully discoverable/activatable now; data lights up when the link
 * provider is supplied. `TODO(48.D)`: provide a real `BluetoothGatt`-client link, scoping the shared
 * SIG `0x2A52` [MedtronicProtocol.RACP_UUID] under the CGM service for [getCgmReading] and under the
 * IDD service for [getHistoryLogs] (the readers reuse the same characteristic UUID across both
 * services; the on-device link must resolve it by service -- `TODO(48.C3)` carried forward).
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
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlin.coroutines.resume
import timber.log.Timber

/**
 * Bundles the Medtronic read layer behind suspend `Result<T>` calls for the capability delegates.
 *
 * @param sessionProvider supplies the live post-handshake session (the connection manager's
 *     `sakeSession`), or `null` when no pump is authenticated.
 * @param linkProvider supplies the GATT-client transport to the connected pump, or `null` when the
 *     transport is unavailable (the deferred Milestone D seam; see the class header).
 * @param ioDispatcher dispatcher for the blocking SIG reads (Device Info / Battery).
 * @param operationTimeoutMs hard upper bound on every read; expiry surfaces as a failed [Result].
 */
class MedtronicReadGateway(
    private val sessionProvider: () -> MedtronicSakeSession?,
    private val linkProvider: () -> MedtronicGattLink?,
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
    private val operationTimeoutMs: Long = DEFAULT_OPERATION_TIMEOUT_MS,
) {

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
     * subscribed. The on-device [MedtronicGattLink] (Milestone D) MUST therefore release all
     * outstanding subscriptions for an operation when that operation's coroutine is cancelled, so a
     * timed-out read leaves no dangling notifications. `TODO(48.D)`.
     */
    private suspend fun <T> sessionRead(
        op: String,
        start: (MedtronicGattLink, MedtronicSakeSession, (Result<T>) -> Unit) -> Unit,
    ): Result<T> {
        val link = linkProvider() ?: return notConnected(op, "transport unavailable")
        val session = sessionProvider() ?: return notConnected(op, "no authenticated session")
        return withOperationTimeout(op) {
            // The readers issue blocking GATT read/write before registering their callback, so offload
            // to [ioDispatcher] (as [blockingRead] does); the callback resume is dispatcher-agnostic.
            withContext(ioDispatcher) {
                suspendCancellableCoroutine { cont ->
                    start(link, session) { result -> if (cont.isActive) cont.resume(result) }
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
     * [MedtronicGattLink] (Milestone D) must therefore also enforce its own per-read timeout, as its
     * interface contract requires.
     */
    private suspend fun <T> blockingRead(op: String, read: (MedtronicGattLink) -> T): Result<T> {
        val link = linkProvider() ?: return notConnected(op, "transport unavailable")
        return withOperationTimeout(op) {
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
        // Expected before Milestone D wires the transport; debug (not warn) so it never reads as a
        // Sentry-worthy error while the driver is inert.
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
