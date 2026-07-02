/*
 * AC1: the session-read framework subscribes, reassembles fragmented notifications via PduFramer,
 * decrypts pump->phone payloads with the live SAKE session, and orchestrates the RACP/SOCP
 * request -> notify -> response pattern. Driven by a fake link + frames minted by a real two-sided
 * SAKE handshake (the pump role's client_crypt), so the decrypt path is genuinely exercised.
 */
package com.glycemicgpt.mobile.ble.read

import com.glycemicgpt.mobile.ble.protocol.MedtronicProtocol
import com.glycemicgpt.mobile.ble.protocol.PduFramer
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MedtronicSessionReaderTest {

    private val dataChar = MedtronicProtocol.CGM_MEASUREMENT_UUID
    private val racp = MedtronicProtocol.RACP_UUID
    private val socp = MedtronicProtocol.CGM_SOCP_UUID

    @Test
    fun `reportLastRecord decrypts the measurement and completes on the RACP success response`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        val record = hex("0ec3f900f40b000074e00a00e0f1")
        link.onWrite = { characteristic, value ->
            if (characteristic == racp && value.contentEquals(MedtronicSessionReader.RACP_REPORT_LAST_RECORD)) {
                emit(dataChar, two.pumpEncrypt(record))
                emit(racp, MedtronicSessionReader.RACP_REPORT_SUCCESS)
            }
        }

        var result: Result<ByteArray>? = null
        MedtronicSessionReader(link, two.server).reportLastRecord(dataChar, racp) { result = it }

        assertNotNull(result)
        assertTrue(result!!.isSuccess)
        assertArrayEquals(record, result!!.getOrNull())
        // Subscriptions are released once the exchange finishes.
        assertFalse(link.isSubscribed(dataChar))
        assertFalse(link.isSubscribed(racp))
    }

    @Test
    fun `reportLastRecord reassembles a fragmented measurement before decrypting`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        // A record large enough that its plaintext exceeds one 20-byte PDU and must reassemble.
        val record = ByteArray(25) { it.toByte() }
        // Each plaintext fragment is individually SAKE-encrypted (per-PDU encryption model).
        val pdus = PduFramer.fragment(record).map { two.pumpEncrypt(it) }
        assertTrue("expected fragmentation", pdus.size > 1)
        link.onWrite = { characteristic, _ ->
            if (characteristic == racp) {
                pdus.forEach { emit(dataChar, it) }
                emit(racp, MedtronicSessionReader.RACP_REPORT_SUCCESS)
            }
        }

        var result: Result<ByteArray>? = null
        MedtronicSessionReader(link, two.server).reportLastRecord(dataChar, racp) { result = it }

        assertArrayEquals(record, result!!.getOrThrow())
    }

    @Test
    fun `reportLastRecord fails when the record is still unterminated at the RACP success response`() {
        // The exact-multiple ambiguity: a record whose plaintext is an exact multiple of the PDU size
        // has no short terminator, so the reassembler is still holding fragments when the terminal
        // indication arrives. Reporting "no record" here would silently misreport what the pump sent.
        val two = TwoSidedSession()
        val link = FakeGattLink()
        val record = ByteArray(PduFramer.MAX_PDU_SIZE * 2) { it.toByte() } // 40 bytes: two full fragments
        val pdus = PduFramer.fragment(record).map { two.pumpEncrypt(it) }
        link.onWrite = { characteristic, _ ->
            if (characteristic == racp) {
                pdus.forEach { emit(dataChar, it) }
                emit(racp, MedtronicSessionReader.RACP_REPORT_SUCCESS)
            }
        }

        var result: Result<ByteArray>? = null
        MedtronicSessionReader(link, two.server).reportLastRecord(dataChar, racp) { result = it }

        assertTrue(result!!.isFailure)
        assertTrue(result!!.exceptionOrNull()!!.message!!.contains("unterminated"))
    }

    @Test
    fun `reportLastRecord fails on an unsuccessful RACP response`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.onWrite = { characteristic, _ ->
            if (characteristic == racp) {
                emit(dataChar, two.pumpEncrypt(hex("0ec3f900f40b000074e00a00e0f1")))
                // Response Code / Null / req 0x01 / 0x06 (procedure not completed) -> not success.
                emit(racp, byteArrayOf(0x06, 0x00, 0x01, 0x06))
            }
        }

        var result: Result<ByteArray>? = null
        MedtronicSessionReader(link, two.server).reportLastRecord(dataChar, racp) { result = it }

        assertTrue(result!!.isFailure)
    }

    @Test
    fun `reportLastRecord fails when the measurement does not authenticate`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        val tampered = two.pumpEncrypt(hex("0ec3f900f40b000074e00a00e0f1")).also { it[0] = (it[0] + 1).toByte() }
        link.onWrite = { characteristic, _ ->
            if (characteristic == racp) {
                emit(dataChar, tampered)
                emit(racp, MedtronicSessionReader.RACP_REPORT_SUCCESS)
            }
        }

        var result: Result<ByteArray>? = null
        MedtronicSessionReader(link, two.server).reportLastRecord(dataChar, racp) { result = it }

        assertTrue(result!!.isFailure)
        assertTrue(result!!.exceptionOrNull() is MedtronicReadException)
    }

    @Test
    fun `reportLastRecord fails when a peer streams full PDUs past the frame cap`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.onWrite = { characteristic, _ ->
            if (characteristic == racp) {
                // Stream full-size PDUs with no short terminator past MAX_FRAME_SIZE (512).
                repeat(30) { emit(dataChar, ByteArray(PduFramer.MAX_PDU_SIZE) { 0x41 }) }
                emit(racp, MedtronicSessionReader.RACP_REPORT_SUCCESS)
            }
        }

        var result: Result<ByteArray>? = null
        MedtronicSessionReader(link, two.server).reportLastRecord(dataChar, racp) { result = it }

        assertTrue(result!!.isFailure)
        assertTrue(result!!.exceptionOrNull() is MedtronicReadException)
    }

    @Test
    fun `socpGet ignores a notification delivered after the exchange finished`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        val results = mutableListOf<Result<ByteArray>>()
        link.onWrite = { characteristic, _ ->
            if (characteristic == socp) emit(socp, two.pumpEncrypt(hex("9100")))
        }

        MedtronicSessionReader(link, two.server).socpGet(socp, byteArrayOf(0x90.toByte())) { results.add(it) }
        assertEquals(1, results.size)
        assertArrayEquals(hex("9100"), results[0].getOrThrow())

        // A duplicate/late notification still in flight when the reader unsubscribed must be dropped:
        // the post-finish guard stops a second decryptFromPump that would consume a sequence slot.
        link.emitInFlight(socp, two.pumpEncrypt(hex("dead")))
        assertEquals(1, results.size)
    }

    @Test
    fun `reportLastRecord ignores a measurement delivered after the exchange finished`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        val results = mutableListOf<Result<ByteArray>>()
        link.onWrite = { characteristic, _ ->
            if (characteristic == racp) {
                emit(dataChar, two.pumpEncrypt(hex("0ec3f900f40b000074e00a00e0f1")))
                emit(racp, MedtronicSessionReader.RACP_REPORT_SUCCESS)
            }
        }

        MedtronicSessionReader(link, two.server).reportLastRecord(dataChar, racp) { results.add(it) }
        assertEquals(1, results.size)
        assertTrue(results[0].isSuccess)

        link.emitInFlight(dataChar, two.pumpEncrypt(hex("0ec38d00e803000010e00a00d9af")))
        assertEquals(1, results.size)
    }

    @Test
    fun `socpGet encrypts the request and decrypts the response`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        val request = byteArrayOf(0x90.toByte()) // GET_SENSOR_DETAILS opcode
        val responsePlain = hex("91071d00ffff60273420") // SENSOR_DETAILS_RESPONSE (sensor_details.py)
        link.onWrite = { characteristic, value ->
            if (characteristic == socp) {
                // The request crossed the link encrypted, not in the clear.
                assertFalse(value.contentEquals(request))
                emit(socp, two.pumpEncrypt(responsePlain))
            }
        }

        var result: Result<ByteArray>? = null
        MedtronicSessionReader(link, two.server).socpGet(socp, request) { result = it }

        assertArrayEquals(responsePlain, result!!.getOrThrow())
        assertEquals(1, link.writes.size)
    }
}
