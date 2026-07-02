/*
 * Post-handshake session-read framework for the Medtronic MiniMed 700-series read-only driver.
 *
 * GlycemicGPT code (GPL-3.0). The control-point read choreography -- write a request, collect the
 * (possibly fragmented, SAKE-encrypted) notifications, terminate on the response -- mirrors
 * OpenMinimed's PythonPumpConnector `sg_reader.py` (SGReader) and `socp.py` (SocpController),
 * GPL-3.0, used with the author's permission; the SAKE cipher itself lives in the vendored JavaSake
 * behind MedtronicSakeSession (B1). See medtronic-ble-reverse-engineering.md Sec. 8.
 */
package com.glycemicgpt.mobile.ble.read

import com.glycemicgpt.mobile.ble.protocol.PduFramer
import com.glycemicgpt.mobile.ble.sake.MedtronicSakeSession
import java.util.UUID
import timber.log.Timber

/**
 * Accumulates inbound notification fragments into a complete application frame.
 *
 * Each notification PDU is individually SAKE-encrypted, so what is offered here is the decrypted
 * *plaintext* fragment. Frames fragment at 20 bytes ([PduFramer.MAX_PDU_SIZE]); the standard BLE
 * convention used here is "full fragments until a short one ends the frame", so a frame is complete
 * when a fragment smaller than [maxPduSize] arrives (a single short fragment completes immediately).
 * This is the incremental inverse of [PduFramer.fragment] for any payload whose length is not an
 * exact multiple of [maxPduSize].
 *
 * The exact-multiple ambiguity (a frame that fragments into all-full fragments has no short
 * terminator) has not bitten on live multi-PDU history reads (PR #852); pinning the exact on-wire
 * fragment sizes rides with the 48.A2 capture work.
 */
internal class NotificationReassembler(
    private val maxPduSize: Int = PduFramer.MAX_PDU_SIZE,
    private val maxFrameSize: Int = MAX_FRAME_SIZE,
) {
    private val fragments = ArrayList<ByteArray>()
    private var accumulated = 0

    /**
     * Offer one inbound PDU; returns the reassembled frame once complete, or `null` if more PDUs are
     * expected. Empty PDUs are ignored (a real encrypted frame is never empty, so an empty
     * notification is noise and must not falsely terminate a multi-PDU frame).
     *
     * @throws MedtronicReadException if the accumulated frame exceeds [maxFrameSize] -- a peer that
     *     streams only full-size PDUs with no short terminator cannot grow memory without bound.
     */
    fun offer(pdu: ByteArray): ByteArray? {
        if (pdu.isEmpty()) return null
        // Defensive copy: the link may recycle the delivery buffer after the callback returns (the
        // same discipline SakeHandshakeDriver uses on inbound writes).
        fragments.add(pdu.copyOf())
        accumulated += pdu.size
        if (accumulated > maxFrameSize) {
            reset()
            throw MedtronicReadException("Reassembled frame exceeds $maxFrameSize bytes; aborting read")
        }
        if (pdu.size < maxPduSize) {
            val frame = PduFramer.reassemble(fragments)
            reset()
            return frame
        }
        return null
    }

    /** Discard any partially-accumulated frame. */
    fun reset() {
        fragments.clear()
        accumulated = 0
    }

    companion object {
        /**
         * Upper bound on a single reassembled application frame. Far above any CGM/SOCP record, it
         * caps the memory a malfunctioning or hostile central can force by streaming full-size PDUs
         * without a short terminator. Record-level paging for the larger history reads is 48.C2.
         */
        const val MAX_FRAME_SIZE = 512
    }
}

/**
 * Reusable read layer over a live [MedtronicSakeSession]: subscribes to a characteristic, reassembles
 * fragmented notifications, decrypts pump->phone payloads, and orchestrates the control-point
 * request -> notify -> response pattern shared by the RACP (CGM single-record + IDD multi-record),
 * SOCP and IDD SRCP exchanges, plus encrypted static reads (IDD Status/Features).
 *
 * **Read-only.** Only report/get-class requests are issued; no control or calibration opcode is ever
 * written.
 *
 * The exchanges are event-driven and complete via the supplied callback. They assume the link
 * delivers all notification callbacks serialized on a single thread (the contract on
 * [MedtronicGattLink]); the per-exchange state is confined to that thread and not otherwise
 * synchronized.
 *
 * **Timeout contract:** this framework carries no timers so it stays transport-agnostic and
 * unit-testable; if the pump never responds, the callback is never invoked. Per the project's BLE
 * guideline ("all BLE operations must have timeouts"), the on-device caller (the C3
 * `BluetoothGatt`-client wiring) **must** bound every exchange with an operation timeout and surface
 * expiry as a [MedtronicReadException] -- e.g. by wrapping these calls in a coroutine with
 * `withTimeout`. The pure logic here is the request/decrypt/reassemble/terminate choreography only.
 */
class MedtronicSessionReader(
    private val link: MedtronicGattLink,
    private val session: MedtronicSakeSession,
) {

    /**
     * RACP "Report Stored Records: Last Record": write the (plaintext) request to [controlPoint],
     * collect the SAKE-encrypted measurement notification on [dataChar], decrypt it, and finish when
     * the plaintext RACP response indication confirms success.
     *
     * Delivers the decrypted record bytes via [onResult]; a failure (CRC/MAC, an unsuccessful or
     * unexpected RACP response, or a missing record) is delivered as [Result.failure]. [onResult] is
     * invoked only when the pump responds (or errors); the caller must impose the operation timeout
     * (see the class-level timeout contract).
     */
    fun reportLastRecord(
        dataChar: UUID,
        controlPoint: UUID,
        onResult: (Result<ByteArray>) -> Unit,
    ) {
        val assembler = NotificationReassembler()
        var record: ByteArray? = null
        var finished = false

        fun finish(result: Result<ByteArray>) {
            if (finished) return
            finished = true
            link.unsubscribe(dataChar)
            link.unsubscribe(controlPoint)
            onResult(result)
        }

        link.subscribe(dataChar) { pdu ->
            if (finished) return@subscribe
            try {
                // Each notification PDU is individually SAKE-encrypted with its own 3-byte trailer.
                // Decrypt first, then reassemble plaintext fragments into the complete record.
                val plaintext = session.decryptFromPump(pdu)
                val frame = assembler.offer(plaintext) ?: return@subscribe
                record = frame
            } catch (e: Exception) {
                // Any decrypt/auth failure (MacFailureException) or session-state/length error
                // (IllegalState/IllegalArgument from SeqCrypt) must fail the read cleanly rather than
                // escape the delivery thread and leave the exchange hung, matching SakeHandshakeDriver.
                finish(Result.failure(asReadException(e, "CGM measurement could not be decrypted")))
            }
        }

        link.subscribe(controlPoint) { response ->
            if (finished) return@subscribe
            Timber.d("CGM RACP response (%d bytes) %s", response.size, response.toHex())
            when {
                response.contentEquals(RACP_REPORT_SUCCESS) -> {
                    val r = record
                    if (r == null) {
                        finish(Result.failure(MedtronicReadException("CGM RACP reported success but no record arrived")))
                    } else {
                        finish(Result.success(r))
                    }
                }
                else -> finish(
                    Result.failure(
                        MedtronicReadException("Unexpected CGM RACP response: ${response.toHex()}"),
                    ),
                )
            }
        }

        Timber.d("CGM RACP report-last-record request (%d bytes) %s", RACP_REPORT_LAST_RECORD.size, RACP_REPORT_LAST_RECORD.toHex())
        try {
            link.write(controlPoint, RACP_REPORT_LAST_RECORD)
        } catch (e: Exception) {
            finish(Result.failure(asReadException(e, "CGM RACP write failed")))
        }
    }

    /**
     * SOCP read-only GET (e.g. sensor details): take a [requestOpcode] (a GET-class opcode, optionally
     * followed by operands), append the E2E-CRC and SAKE-encrypt it for the pump exactly as
     * `socp.py._trigger_opcode` does, write it to the [socp] characteristic, then decrypt each
     * SAKE-encrypted response PDU and reassemble the plaintext, delivering it (its first byte is the response opcode; any
     * E2E-CRC trailer is validated by the response parser in 48.C2). Only GET-class opcodes belong here
     * -- no calibration or control opcode is ever issued. As with [reportLastRecord], the caller must
     * impose the operation timeout (see the class-level timeout contract).
     */
    fun socpGet(socp: UUID, requestOpcode: ByteArray, onResult: (Result<ByteArray>) -> Unit) {
        val request = appendE2eCrc(requestOpcode)
        Timber.d("CGM SOCP GET request (%d bytes) %s", request.size, request.toHex())
        encryptedGet(socp, session.encryptForPump(request), "SOCP response could not be decrypted", onResult)
    }

    /**
     * IDD Status Reader Control Point (SRCP) read-only GET: SAKE-encrypt the (little-endian)
     * [requestOpcode], write it to the [srcp] characteristic, then decrypt each SAKE-encrypted
     * indication PDU and reassemble + deliver the plaintext, exactly as `idd/status/reader.py`'s
     * `_send_and_receive_opcode` does. Only GET-class opcodes (IOB, active basal, therapy state, ...)
     * belong here -- no reset or control opcode is ever issued.
     *
     * Unlike [socpGet] the request is **not** E2E-CRC-wrapped: the 780G does not enable E2E
     * protection in the IDD service, and upstream reads the IDD Features E2E bit to decide rather than
     * assuming. `TODO(48.A2)`: honor that features flag per model once a live pump confirms it. As
     * with the other exchanges the caller must impose the operation timeout.
     */
    fun srcpGet(srcp: UUID, requestOpcode: ByteArray, onResult: (Result<ByteArray>) -> Unit) {
        Timber.d("IDD SRCP GET request (%d bytes) %s", requestOpcode.size, requestOpcode.toHex())
        encryptedGet(srcp, session.encryptForPump(requestOpcode), "IDD SRCP response could not be decrypted", onResult)
    }

    /**
     * Read a SAKE-encrypted static characteristic (e.g. IDD Status `0x102`) and decrypt it. Unlike the
     * plain [MedtronicGattLink.read] used for SIG characteristics, the IDD Status/Features values are
     * encrypted, so they are decrypted here exactly as `idd/status/reader.py`'s `get_pump_status`
     * does (`server_crypt.decrypt` of the raw read).
     *
     * Decrypting advances the session's inbound sequence counter, so this must be ordered with the
     * other reads against the same session. Synchronous: the underlying [MedtronicGattLink.read] is.
     *
     * @throws MedtronicReadException if the read fails or the value does not authenticate/decrypt.
     */
    fun decryptedRead(characteristic: UUID): ByteArray =
        try {
            session.decryptFromPump(link.read(characteristic))
        } catch (e: Exception) {
            throw asReadException(e, "Encrypted characteristic $characteristic could not be decrypted")
        }

    /**
     * Multi-record RACP report: write the (plaintext) [request] to [controlPoint], collect the stream
     * of SAKE-encrypted record notifications on [dataChar] -- decrypting each -- and terminate when the
     * plaintext RACP indication arrives. [isSuccess] decides whether that terminating indication is a
     * success (deliver the collected records) or a failure (e.g. an IDD RACP error code).
     *
     * Mirrors `history_reader.py` (`get_records_between` / `get_last_record`): the RACP itself is not
     * encrypted, only the IDD History Data records it triggers are, and the RACP indication follows
     * after all records. Records are delimited by the same short-PDU rule [NotificationReassembler]
     * uses; see the record-framing notes on [HistoryReader]. The caller imposes the operation
     * timeout (class-level contract).
     */
    fun reportRecords(
        dataChar: UUID,
        controlPoint: UUID,
        request: ByteArray,
        isSuccess: (ByteArray) -> Boolean,
        onResult: (Result<List<ByteArray>>) -> Unit,
    ) {
        val assembler = NotificationReassembler()
        val records = ArrayList<ByteArray>()
        var finished = false

        fun finish(result: Result<List<ByteArray>>) {
            if (finished) return
            finished = true
            link.unsubscribe(dataChar)
            link.unsubscribe(controlPoint)
            onResult(result)
        }

        link.subscribe(dataChar) { pdu ->
            if (finished) return@subscribe
            try {
                // Each notification PDU is individually SAKE-encrypted with its own 3-byte trailer.
                // Decrypt first, then reassemble plaintext fragments into the complete record.
                val plaintext = session.decryptFromPump(pdu)
                val frame = assembler.offer(plaintext) ?: return@subscribe
                records.add(frame)
                // Defense-in-depth: a misbehaving (but authenticated) pump that streams records but
                // never sends the terminating RACP indication must not grow memory without bound. The
                // ceiling is far above any realistic single-fetch window; the operation timeout the C3
                // caller imposes is the primary bound (mirrors NotificationReassembler's frame cap).
                if (records.size > MAX_RECORDS_PER_REPORT) {
                    finish(
                        Result.failure(
                            MedtronicReadException(
                                "History report exceeded $MAX_RECORDS_PER_REPORT records without a terminating response",
                            ),
                        ),
                    )
                    return@subscribe
                }
            } catch (e: Exception) {
                finish(Result.failure(asReadException(e, "History record could not be decrypted")))
            }
        }

        link.subscribe(controlPoint) { response ->
            if (finished) return@subscribe
            if (isSuccess(response)) {
                finish(Result.success(records.toList()))
            } else {
                finish(
                    Result.failure(MedtronicReadException("Unexpected/failed IDD RACP response: ${response.toHex()}")),
                )
            }
        }

        Timber.d("IDD RACP report-records request (%d bytes) %s", request.size, request.toHex())
        try {
            link.write(controlPoint, request)
        } catch (e: Exception) {
            finish(Result.failure(asReadException(e, "IDD RACP write failed")))
        }
    }

    /**
     * Single plaintext control-point query (no encrypted data records): write [request] to
     * [controlPoint] and deliver the first RACP indication verbatim. Used for the IDD "report number
     * of records" query (`history_reader.py`'s `get_available_record_count`), where the count rides in
     * the RACP indication itself and the IDD History Data characteristic is not involved.
     */
    fun controlPointQuery(controlPoint: UUID, request: ByteArray, onResult: (Result<ByteArray>) -> Unit) {
        var finished = false

        fun finish(result: Result<ByteArray>) {
            if (finished) return
            finished = true
            link.unsubscribe(controlPoint)
            onResult(result)
        }

        link.subscribe(controlPoint) { response ->
            if (finished) return@subscribe
            finish(Result.success(response.copyOf()))
        }

        Timber.d("IDD RACP control-point query (%d bytes) %s", request.size, request.toHex())
        try {
            link.write(controlPoint, request)
        } catch (e: Exception) {
            finish(Result.failure(asReadException(e, "IDD RACP write failed")))
        }
    }

    /**
     * Shared body for the encrypted request -> single encrypted response exchanges ([socpGet],
     * [srcpGet]): subscribe to [char], decrypt each PDU and reassemble the first complete response
     * frame, and finish. Decrypting only while the exchange is live keeps a late/duplicate notification after
     * finish() from consuming the next operation's sequence slot and desyncing the session.
     */
    private fun encryptedGet(
        char: UUID,
        encryptedRequest: ByteArray,
        failMessage: String,
        onResult: (Result<ByteArray>) -> Unit,
    ) {
        val assembler = NotificationReassembler()
        var finished = false

        fun finish(result: Result<ByteArray>) {
            if (finished) return
            finished = true
            link.unsubscribe(char)
            onResult(result)
        }

        link.subscribe(char) { pdu ->
            if (finished) return@subscribe
            try {
                // Each notification PDU is individually SAKE-encrypted with its own 3-byte trailer.
                // Decrypt first, then reassemble plaintext fragments into the complete response.
                val plaintext = session.decryptFromPump(pdu)
                val frame = assembler.offer(plaintext) ?: return@subscribe
                finish(Result.success(frame))
            } catch (e: Exception) {
                finish(Result.failure(asReadException(e, failMessage)))
            }
        }

        try {
            link.write(char, encryptedRequest)
        } catch (e: Exception) {
            finish(Result.failure(asReadException(e, failMessage)))
        }
    }

    /** Map any decrypt/parse failure to a [MedtronicReadException], preserving an already-typed one. */
    private fun asReadException(e: Exception, message: String): MedtronicReadException =
        e as? MedtronicReadException ?: MedtronicReadException(message, e)

    /** Append the little-endian E2E-CRC over [payload], matching `socp.py`'s request framing. */
    private fun appendE2eCrc(payload: ByteArray): ByteArray {
        val crc = MedtronicCodec.e2eCrc(payload)
        return payload + byteArrayOf((crc and 0xFF).toByte(), ((crc shr 8) and 0xFF).toByte())
    }

    companion object {
        /**
         * RACP request: Op Code 0x01 (Report Stored Records), Operator 0x06 (Last Record). Written in
         * the clear -- the RACP itself is not SAKE-encrypted, only the measurement it triggers is
         * (`sg_reader.py`). The 4-byte RACP response likewise fits a single notification PDU, so it is
         * not run through the reassembler.
         */
        val RACP_REPORT_LAST_RECORD = byteArrayOf(0x01, 0x06)

        /**
         * Expected RACP response: Op Code 0x06 (Response Code), Operator 0x00 (Null), Operand =
         * Request Op Code 0x01 + Response Code Value 0x01 (Success). GSS section 3.199.
         */
        val RACP_REPORT_SUCCESS = byteArrayOf(0x06, 0x00, 0x01, 0x01)

        /**
         * Upper bound on records collected in a single [reportRecords] call before the read is failed.
         * Generous (far above any realistic incremental/backfill window) -- it only bounds memory when
         * a pump streams records but never terminates the RACP procedure.
         */
        const val MAX_RECORDS_PER_REPORT = 50_000

        private fun ByteArray.toHex(): String = MedtronicCodec.toHex(this)
    }
}
