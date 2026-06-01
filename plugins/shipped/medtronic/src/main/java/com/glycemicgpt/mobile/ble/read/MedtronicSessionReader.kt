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
 * Accumulates inbound notification PDUs into a complete application frame.
 *
 * Application frames are fragmented into <= 20-byte PDUs ([PduFramer.fragment]); the standard BLE
 * convention used here is "full PDUs until a short one ends the frame", so a frame is complete when
 * a PDU smaller than [maxPduSize] arrives (a single short PDU completes immediately). This is the
 * incremental inverse of [PduFramer.fragment] for any payload whose length is not an exact multiple
 * of [maxPduSize].
 *
 * The exact-multiple ambiguity (a frame that fragments into all-full PDUs has no short terminator)
 * does not arise for the small SAKE-encrypted CGM records this story handles; record-level,
 * length-prefixed paging for the larger history reads lands with the history reader in 48.C2.
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
 * request -> notify -> response pattern shared by RACP and SOCP.
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
                val frame = assembler.offer(pdu) ?: return@subscribe
                // Decrypting advances the session's inbound sequence counter, so only do it while the
                // exchange is live; a late notification after finish() would desync the next read.
                record = session.decryptFromPump(frame)
            } catch (e: Exception) {
                // Any decrypt/auth failure (MacFailureException) or session-state/length error
                // (IllegalState/IllegalArgument from SeqCrypt) must fail the read cleanly rather than
                // escape the delivery thread and leave the exchange hung, matching SakeHandshakeDriver.
                finish(Result.failure(asReadException(e, "CGM measurement could not be decrypted")))
            }
        }

        link.subscribe(controlPoint) { response ->
            if (finished) return@subscribe
            when {
                response.contentEquals(RACP_REPORT_SUCCESS) -> {
                    val r = record
                    if (r == null) {
                        finish(Result.failure(MedtronicReadException("RACP reported success but no record arrived")))
                    } else {
                        finish(Result.success(r))
                    }
                }
                else -> finish(
                    Result.failure(
                        MedtronicReadException("Unexpected RACP response: ${response.toHex()}"),
                    ),
                )
            }
        }

        Timber.d("RACP report-last-record request")
        link.write(controlPoint, RACP_REPORT_LAST_RECORD)
    }

    /**
     * SOCP read-only GET (e.g. sensor details): take a [requestOpcode] (a GET-class opcode, optionally
     * followed by operands), append the E2E-CRC and SAKE-encrypt it for the pump exactly as
     * `socp.py._trigger_opcode` does, write it to the [socp] characteristic, then reassemble + decrypt
     * the SAKE-encrypted response and deliver the plaintext (its first byte is the response opcode; any
     * E2E-CRC trailer is validated by the response parser in 48.C2). Only GET-class opcodes belong here
     * -- no calibration or control opcode is ever issued. As with [reportLastRecord], the caller must
     * impose the operation timeout (see the class-level timeout contract).
     */
    fun socpGet(socp: UUID, requestOpcode: ByteArray, onResult: (Result<ByteArray>) -> Unit) {
        val assembler = NotificationReassembler()
        var finished = false

        fun finish(result: Result<ByteArray>) {
            if (finished) return
            finished = true
            link.unsubscribe(socp)
            onResult(result)
        }

        link.subscribe(socp) { pdu ->
            try {
                val frame = assembler.offer(pdu) ?: return@subscribe
                finish(Result.success(session.decryptFromPump(frame)))
            } catch (e: Exception) {
                finish(Result.failure(asReadException(e, "SOCP response could not be decrypted")))
            }
        }

        val request = appendE2eCrc(requestOpcode)
        Timber.d("SOCP GET request (%d bytes)", request.size)
        link.write(socp, session.encryptForPump(request))
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

        private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
    }
}
