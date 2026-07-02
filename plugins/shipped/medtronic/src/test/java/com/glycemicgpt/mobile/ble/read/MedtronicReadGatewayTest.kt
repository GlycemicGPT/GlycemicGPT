/*
 * AC1 / AC6 / AC7: the read gateway resolves the live session + transport, bridges the callback/blocking
 * readers to suspend Result<T>, fails cleanly when not connected, and bounds a hung read with the
 * per-operation timeout.
 */
package com.glycemicgpt.mobile.ble.read

import com.glycemicgpt.mobile.ble.protocol.MedtronicProtocol
import com.glycemicgpt.mobile.ble.sake.MedtronicSakeSession
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class MedtronicReadGatewayTest {

    private val feature = MedtronicProtocol.CGM_FEATURE_UUID
    private val measurement = MedtronicProtocol.CGM_MEASUREMENT_UUID
    private val racp = MedtronicProtocol.RACP_UUID

    private fun TestScope.gateway(
        link: MedtronicGattLink?,
        session: MedtronicSakeSession?,
        timeoutMs: Long = 30_000L,
    ) = MedtronicReadGateway(
        sessionProvider = { session },
        linkProvider = { link },
        ioDispatcher = UnconfinedTestDispatcher(testScheduler),
        operationTimeoutMs = timeoutMs,
    )

    @Test
    fun `a session read fails cleanly when no session is held`() = runTest {
        val result = gateway(link = FakeGattLink(), session = null).getCgmReading()
        assertTrue(result.isFailure)
        assertTrue(result.exceptionOrNull() is MedtronicReadException)
    }

    @Test
    fun `a blocking read fails cleanly when the transport is unavailable`() = runTest {
        val result = gateway(link = null, session = TwoSidedSession().server).getBatteryStatus()
        assertTrue(result.isFailure)
        assertTrue(result.exceptionOrNull() is MedtronicReadException)
    }

    @Test
    fun `getBatteryStatus reads the SIG battery level`() = runTest {
        val link = FakeGattLink()
        link.reads[MedtronicProtocol.BATTERY_LEVEL_UUID] = byteArrayOf(85)

        val result = gateway(link = link, session = TwoSidedSession().server).getBatteryStatus()

        assertEquals(85, result.getOrThrow().percentage)
    }

    @Test
    fun `getDeviceInfo reads the Device Information Service`() = runTest {
        val link = FakeGattLink()
        link.reads[MedtronicProtocol.MODEL_NUMBER_UUID] = "MMT-1880".toByteArray()
        link.reads[MedtronicProtocol.SERIAL_NUMBER_UUID] = "NG1234567H".toByteArray()
        link.reads[MedtronicProtocol.HARDWARE_REVISION_UUID] = "RevA".toByteArray()
        link.reads[MedtronicProtocol.FIRMWARE_REVISION_UUID] = "4.2.1".toByteArray()
        link.reads[MedtronicProtocol.SOFTWARE_REVISION_UUID] = "10.5".toByteArray()
        link.reads[MedtronicProtocol.SYSTEM_ID_UUID] = byteArrayOf(0, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77)

        val info = gateway(link = link, session = TwoSidedSession().server).getDeviceInfo().getOrThrow()

        assertEquals("MMT-1880", info.modelNumber)
        assertEquals("NG1234567H", info.serialNumber)
        assertEquals("0011223344556677", info.systemId)
    }

    @Test
    fun `getCgmReading drives the full session read to a parsed reading`() = runTest {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.reads[feature] = hex(CGM_FEATURE_E2E_ENABLED_HEX)
        link.onWrite = { characteristic, _ ->
            if (characteristic == racp) {
                emit(measurement, two.pumpEncrypt(hex(CGM_MEASUREMENT_249_HEX)))
                emit(racp, MedtronicSessionReader.RACP_REPORT_SUCCESS)
            }
        }

        val result = gateway(link = link, session = two.server).getCgmReading()

        assertEquals(249, result.getOrThrow().glucoseMgDl)
    }

    @Test
    fun `a hung read is bounded by the operation timeout`() = runTest {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.reads[feature] = hex(CGM_FEATURE_E2E_ENABLED_HEX)
        // The pump never responds to the RACP request, so the reader's callback never fires.

        val result = gateway(link = link, session = two.server, timeoutMs = 5_000L).getCgmReading()

        assertTrue(result.isFailure)
        val error = result.exceptionOrNull()
        assertTrue(error is MedtronicReadException)
        assertTrue("expected a timeout failure", error!!.message!!.contains("timed out"))
    }

    /**
     * The blocking-read path (battery / device info) must also be bounded: a synchronous GATT read
     * that blocks is not a suspension point, so the gateway uses runInterruptible to make the operation
     * timeout interrupt it. Uses a real IO dispatcher + real (short) timeout so the interrupt actually
     * fires; with a plain withContext this would hang past the deadline.
     */
    @Test
    fun `a hung blocking read is bounded by the operation timeout`() = runBlocking {
        val blockingLink = object : MedtronicGattLink {
            override fun read(characteristic: UUID): ByteArray {
                Thread.sleep(30_000) // never completes within the test budget; only the interrupt ends it
                return ByteArray(0)
            }
            override fun write(characteristic: UUID, value: ByteArray) = error("unused")
            override fun subscribe(characteristic: UUID, onPdu: (ByteArray) -> Unit) = error("unused")
            override fun unsubscribe(characteristic: UUID) = error("unused")
            override fun cancelAllSubscriptions() = error("unused")
        }
        val gateway = MedtronicReadGateway(
            sessionProvider = { TwoSidedSession().server },
            linkProvider = { blockingLink },
            ioDispatcher = Dispatchers.IO,
            operationTimeoutMs = 200L,
        )

        val result = gateway.getBatteryStatus()

        assertTrue(result.isFailure)
        assertTrue(result.exceptionOrNull()!!.message!!.contains("timed out"))
    }

    /**
     * Single-flight (Story AC1): the Medtronic link is one-exchange-at-a-time, but the polling
     * orchestrator drives the fast/medium/slow tiers as independent coroutines, so the gateway must
     * serialize them. Two concurrent reads are launched eagerly; the first holds the link awaiting its
     * (deferred) response, so the second must park on the gateway's mutex and reach the wire only after
     * the first finishes -- exactly one RACP write is outstanding at a time, never two overlapping.
     */
    @Test
    fun `concurrent reads are serialized single-flight on the one link`() = runTest {
        val two = TwoSidedSession()
        val link = SerializingProbeLink(two)
        val io = UnconfinedTestDispatcher(testScheduler)
        val gw = MedtronicReadGateway(
            sessionProvider = { two.server },
            linkProvider = { link },
            ioDispatcher = io,
            operationTimeoutMs = 30_000L,
        )

        // Eagerly dispatched (Unconfined): each runs until it suspends. The first parks awaiting the
        // pump's deferred response while holding the mutex; the second parks on the mutex itself.
        val first = async(io) { gw.getCgmReading() }
        val second = async(io) { gw.getCgmReading() }

        // The proof: only the first exchange has reached the wire. Without single-flight the second
        // would already have written its own RACP request (racpWrites == 2).
        assertEquals("second read must not touch the link while the first holds it", 1, link.racpWrites)

        link.releaseNext() // complete the first; releasing the mutex lets the second proceed
        assertEquals("second read reaches the wire only after the first finishes", 2, link.racpWrites)

        link.releaseNext() // complete the second

        assertEquals(249, first.await().getOrThrow().glucoseMgDl)
        assertEquals(249, second.await().getOrThrow().glucoseMgDl)
    }

    // -- History paging (getHistoryLogs) -------------------------------------

    @Test
    fun `getHistoryLogs pages by requested window so a sparse page cannot skip older records`() = runTest {
        val two = TwoSidedSession()
        val pump = ScriptedHistoryPump(two, retainedSequences = listOf(150, 400))

        val records = gateway(link = pump.link, session = two.server).getHistoryLogs(sinceSequence = 0).getOrThrow()

        assertEquals(listOf(150, 400), records.map { it.sequenceNumber })
        // Window-driven walk: the first page parses sparse (1 record in a 200-sequence window) yet the
        // walk continues into the next window. Content-driven paging would stop after the first page
        // and -- because the callers advance their cursor to the max sequence seen -- skip record 150
        // permanently.
        assertEquals(listOf(201..400, 1..200), pump.rangeRequests)
    }

    @Test
    fun `getHistoryLogs stops paging at the pump's oldest retained record`() = runTest {
        val two = TwoSidedSession()
        val pump = ScriptedHistoryPump(two, retainedSequences = (950..1000).toList())

        val records = gateway(link = pump.link, session = two.server).getHistoryLogs(sinceSequence = 0).getOrThrow()

        assertEquals((950..1000).toList(), records.map { it.sequenceNumber })
        // The pump purges oldest-first, so the window below the retained tail answers "no records
        // found" (an empty page) and the walk ends there -- no futile scan down to sequence 1.
        assertEquals(listOf(801..1000, 601..800), pump.rangeRequests)
    }

    @Test
    fun `getHistoryLogs returns multi-page results in ascending sequence order`() = runTest {
        val two = TwoSidedSession()
        val pump = ScriptedHistoryPump(two, retainedSequences = (1..450).toList())

        val records = gateway(link = pump.link, session = two.server).getHistoryLogs(sinceSequence = 50).getOrThrow()

        assertEquals((51..450).toList(), records.map { it.sequenceNumber })
    }

    @Test
    fun `getHistoryLogs is empty when already caught up`() = runTest {
        val two = TwoSidedSession()
        val pump = ScriptedHistoryPump(two, retainedSequences = listOf(100))

        val records = gateway(link = pump.link, session = two.server).getHistoryLogs(sinceSequence = 100).getOrThrow()

        assertTrue(records.isEmpty())
        assertTrue(pump.rangeRequests.isEmpty())
    }

    @Test
    fun `getHistoryLogs fails once the walk accumulates past the total-record ceiling`() = runTest {
        // The cross-page analog of MAX_RECORDS_PER_REPORT: a malfunctioning (but authenticated) pump
        // reporting a bogus huge last-sequence and answering every window must not grow memory
        // without bound. Failing leaves the cursors put, so nothing is silently skipped.
        val two = TwoSidedSession()
        val pump = ScriptedHistoryPump(two, retainedSequences = (1..450).toList())
        val gw = MedtronicReadGateway(
            sessionProvider = { two.server },
            linkProvider = { pump.link },
            ioDispatcher = UnconfinedTestDispatcher(testScheduler),
            maxTotalHistoryRecords = 300,
        )

        val result = gw.getHistoryLogs(sinceSequence = 0)

        assertTrue(result.isFailure)
        assertTrue(result.exceptionOrNull()!!.message!!.contains("exceeded 300 records"))
    }

    @Test
    fun `getHistoryLogs fails the whole fetch when a page fails`() = runTest {
        // Older pages are still un-fetched when a page fails; returning the newer pages collected so
        // far would let the callers advance their cursor past the gap and skip those records for good.
        val two = TwoSidedSession()
        val pump = ScriptedHistoryPump(two, retainedSequences = (1..450).toList())
        pump.failWindowsBelow = 251 // the first page succeeds, the second page errors

        val result = gateway(link = pump.link, session = two.server).getHistoryLogs(sinceSequence = 50)

        assertTrue(result.isFailure)
    }

    /**
     * Scripts a pump's IDD history service on a [FakeGattLink]: answers the last-record request with
     * the newest retained record and each within-range request with the retained records in that
     * window -- or the "no records found" indication when the window is empty, as a real pump does
     * once a walk crosses its oldest retained record. Every frame is freshly SAKE-encrypted at
     * delivery time so the two-sided session's sequence counters stay aligned across pages.
     */
    private class ScriptedHistoryPump(
        private val two: TwoSidedSession,
        retainedSequences: List<Int>,
    ) {
        val link = FakeGattLink()
        val rangeRequests = mutableListOf<IntRange>()

        /** Windows whose first sequence is below this fail with an RACP error (for failure tests). */
        var failWindowsBelow = Int.MIN_VALUE

        private val retained = retainedSequences.toSortedSet()
        private val racp = MedtronicProtocol.RACP_UUID
        private val data = MedtronicProtocol.IDD_HISTORY_DATA_UUID

        init {
            link.onRead = { characteristic ->
                if (characteristic == MedtronicProtocol.IDD_FEATURES_UUID) two.pumpEncrypt(hex(IDD_FEATURES_E2E_DISABLED_HEX)) else null
            }
            link.onWrite = { characteristic, value ->
                if (characteristic == racp) respond(value)
            }
        }

        private fun respond(request: ByteArray) {
            when {
                request.contentEquals(HistoryReader.REQUEST_REPORT_LAST_RECORD) -> {
                    val newest = retained.last()
                    emitRecord(newest)
                    link.emit(racp, HistoryReader.EXPECTED_REPORT_SUCCESS)
                }
                request.size == 11 && request[0] == HistoryReader.REQUEST_REPORT_WITHIN_RANGE_PREFIX[0] -> {
                    val first = MedtronicCodec.readULongLe(request, 3, 4).toInt()
                    val last = MedtronicCodec.readULongLe(request, 7, 4).toInt()
                    rangeRequests.add(first..last)
                    if (first < failWindowsBelow) {
                        link.emit(racp, byteArrayOf(0x0F, 0x0F, 0x33, 0x02)) // op-code-not-supported
                        return
                    }
                    val inWindow = retained.subSet(first, last + 1)
                    if (inWindow.isEmpty()) {
                        link.emit(racp, HistoryReader.REPORT_NO_RECORDS_FOUND)
                    } else {
                        inWindow.forEach { emitRecord(it) }
                        link.emit(racp, HistoryReader.EXPECTED_REPORT_SUCCESS)
                    }
                }
            }
        }

        private fun emitRecord(seq: Int) {
            link.emit(data, two.pumpEncrypt(historyRecord(seq)))
        }

        /** An 18-byte basal-rate-changed record (single PDU): type 0x0099, [seq], offset 0. */
        private fun historyRecord(seq: Int): ByteArray =
            byteArrayOf(0x99.toByte(), 0x00) + MedtronicCodec.u32Le(seq) + byteArrayOf(0, 0) + hex("010a0000ff050000ff55")

        companion object {
            /** IDD Features characteristic value with E2E protection disabled. */
            private const val IDD_FEATURES_E2E_DISABLED_HEX = "ffff006400fede801f"
        }
    }

    /**
     * A [MedtronicGattLink] that defers each RACP exchange's response until [releaseNext], so a read
     * stays in flight (holding the single-flight lock) until the test chooses to complete it. Counts
     * RACP writes so a test can prove that a second exchange does not reach the wire while a first is
     * outstanding. Only valid under single-flight (one set of handlers registered at a time).
     */
    private class SerializingProbeLink(private val two: TwoSidedSession) : MedtronicGattLink {
        private val handlers = mutableMapOf<UUID, (ByteArray) -> Unit>()
        private val pendingResponses = ArrayDeque<() -> Unit>()

        var racpWrites = 0
            private set

        override fun read(characteristic: UUID): ByteArray =
            if (characteristic == MedtronicProtocol.CGM_FEATURE_UUID) hex(CGM_FEATURE_E2E_ENABLED_HEX)
            else throw MedtronicReadException("no read stub for $characteristic")

        override fun write(characteristic: UUID, value: ByteArray) {
            if (characteristic != MedtronicProtocol.RACP_UUID) return
            racpWrites++
            // Defer the pump's response so the exchange stays in flight, holding the single-flight lock
            // until releaseNext() delivers it.
            pendingResponses.addLast {
                handlers[MedtronicProtocol.CGM_MEASUREMENT_UUID]
                    ?.invoke(two.pumpEncrypt(hex(CGM_MEASUREMENT_249_HEX)))
                handlers[MedtronicProtocol.RACP_UUID]?.invoke(MedtronicSessionReader.RACP_REPORT_SUCCESS)
            }
        }

        override fun subscribe(characteristic: UUID, onPdu: (ByteArray) -> Unit) {
            handlers[characteristic] = onPdu
        }

        override fun unsubscribe(characteristic: UUID) {
            handlers.remove(characteristic)
        }

        override fun cancelAllSubscriptions() {
            handlers.clear()
            pendingResponses.clear()
        }

        /** Deliver the next deferred pump response, completing the oldest in-flight exchange. */
        fun releaseNext() = pendingResponses.removeFirst().invoke()
    }
}
