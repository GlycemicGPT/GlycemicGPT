/*
 * IDD history/event-log reader for the Medtronic MiniMed 700-series read-only driver.
 *
 * GlycemicGPT code (GPL-3.0). The RACP record-fetch choreography -- query the record count, request
 * the last record or a sequence range, collect the SAKE-encrypted records on the IDD History Data
 * characteristic, and terminate on the (plaintext) RACP indication -- is ported from OpenMinimed
 * PythonPumpConnector `history_reader.py` (HistoryReader), GPL-3.0, used with the author's
 * permission. Copyright (C) OpenMinimed contributors: palmarci (Pal Marci), drfubar, Morten Fyhn
 * Amundsen, Stenium; original medtronic-bt-decrypt PoC by @planiitis. GlycemicGPT is itself GPL-3.0.
 *
 * READ-ONLY: only RACP report/count opcodes are issued; never delete/abort or any write/control
 * opcode. See medtronic-ble-reverse-engineering.md Sec. 8.
 */
package com.glycemicgpt.mobile.ble.read

import com.glycemicgpt.mobile.ble.messages.MedtronicHistoryParser
import com.glycemicgpt.mobile.ble.protocol.MedtronicProtocol
import com.glycemicgpt.mobile.ble.sake.MedtronicSakeSession
import com.glycemicgpt.mobile.domain.model.HistoryLogRecord

/**
 * Reads the pump's IDD event-log (bolus / basal / sensor / alarm / cartridge-battery events) over the
 * C1 session-read framework, preserving each record raw ([HistoryLogRecord], the Tandem `RawHistoryLog`
 * analog) for dedup/backfill. Parsing into typed events + domain models is [MedtronicHistoryParser].
 *
 * **History uses the IDD service's RACP**, not the CGM RACP: upstream's working history path is
 * `history_reader.py` over the IDD Record Access Control Point + IDD History Data (`0x108`); the HAT
 * service (`0x300`) RACP is stubbed/unsupported upstream (`hats.py` -- every request returns
 * "Not Supported" / "No Records Found"), so it is intentionally not used here. The IDD RACP shares the
 * SIG `0x2A52` UUID with the CGM RACP but lives under a different service; the C3 `BluetoothGatt`-client
 * wiring must address [MedtronicProtocol.RACP_UUID] under the IDD service for these reads
 * (`TODO(48.C3)` for the on-device service scoping).
 *
 * **Record framing.** Each notification PDU is individually SAKE-encrypted (its own 3-byte trailer);
 * the C1 reassembler delimits records on the decrypted *plaintext* fragments by its short-PDU rule (a
 * fragment shorter than 20 bytes ends the record). Live 780G reads through this path MAC-pass on
 * multi-PDU records (PR #852), which is cryptographic proof of the per-PDU model -- and implies the
 * pump's notifications exceed the 20-byte payload of a default MTU-23 link (we never `requestMtu()`,
 * but the ATT MTU is per-bearer and the pump raises it from its side; see [PduFramer]). A record whose
 * plaintext is an exact multiple of the fragment size has no short terminator -- the documented
 * [NotificationReassembler] ambiguity; `TODO(48.A2)` to pin the exact on-wire fragment sizes from a
 * live capture. As with the other readers the caller (C3) imposes the per-operation timeout.
 */
class HistoryReader(
    private val link: MedtronicGattLink,
    session: MedtronicSakeSession,
) {
    private val sessionReader = MedtronicSessionReader(link, session)

    /** Available history record count (RACP "report number of records"). */
    fun readRecordCount(onResult: (Result<Int>) -> Unit) {
        sessionReader.controlPointQuery(MedtronicProtocol.RACP_UUID, REQUEST_REPORT_NUMBER_OF_RECORDS) { result ->
            onResult(result.mapCatching { parseCount(it) })
        }
    }

    /** The most recent history record, or `null` if the log is empty / no record arrives. */
    fun readLastRecord(onResult: (Result<HistoryLogRecord?>) -> Unit) {
        val e2e = e2eFlagOr(onResult) ?: return
        fetchRecords(REQUEST_REPORT_LAST_RECORD, e2e) { result ->
            onResult(result.mapCatching { it.firstOrNull() })
        }
    }

    /**
     * All records with sequence number in [firstSeq]..[lastSeq] inclusive. A window the pump holds no
     * records for (the RACP "no records found" indication) is a successful empty list, not a failure
     * -- the gateway's paging walk relies on that to detect the oldest retained record.
     */
    fun readRecordsInRange(firstSeq: Int, lastSeq: Int, onResult: (Result<List<HistoryLogRecord>>) -> Unit) {
        val e2e = e2eFlagOr(onResult) ?: return
        fetchRecords(rangeRequest(firstSeq, lastSeq), e2e, onResult)
    }

    /** Read the IDD Features E2E flag, routing a read/parse failure to [onResult]; null = abort. */
    private fun <T> e2eFlagOr(onResult: (Result<T>) -> Unit): Boolean? =
        try {
            IddFeatures.parse(sessionReader.decryptedRead(MedtronicProtocol.IDD_FEATURES_UUID)).e2eProtectionEnabled
        } catch (e: MedtronicReadException) {
            onResult(Result.failure(e))
            null
        }

    private fun fetchRecords(request: ByteArray, useE2e: Boolean, onResult: (Result<List<HistoryLogRecord>>) -> Unit) {
        sessionReader.reportRecords(
            dataChar = MedtronicProtocol.IDD_HISTORY_DATA_UUID,
            controlPoint = MedtronicProtocol.RACP_UUID,
            request = request,
            isSuccess = ::isReportSuccess,
        ) { result ->
            onResult(
                result.mapCatching { frames ->
                    val parsed = frames.mapNotNull { MedtronicHistoryParser.toHistoryLogRecord(it, useE2e) }
                    // Any undecodable frame must fail the read, not silently shrink the page: the
                    // gateway's walk advances past this window and the callers advance their cursor to
                    // the max sequence seen, so a dropped record would be skipped for good (this is
                    // bolus history feeding IOB). Failing leaves the cursor put and the read retried.
                    // Checked before dedup -- duplicate frames legitimately shrink the list.
                    if (parsed.size < frames.size) {
                        throw MedtronicReadException(
                            "${frames.size - parsed.size} of ${frames.size} history frames in the page were undecodable",
                        )
                    }
                    MedtronicHistoryParser.dedupBySequence(parsed)
                },
            )
        }
    }

    private fun parseCount(response: ByteArray): Int {
        if (response.size < 4) {
            throw MedtronicReadException("IDD RACP count response too short: ${response.size} bytes")
        }
        if (response[0].toInt() and 0xFF != NUMBER_OF_RECORDS_RESPONSE ||
            response[1].toInt() and 0xFF != FILTER_SEQUENCE_NUMBER
        ) {
            throw MedtronicReadException("Unexpected IDD RACP count response: ${response.toHex()}")
        }
        return MedtronicCodec.readUIntLe(response, 2, 2)
    }

    /**
     * True when the terminating RACP indication completes the exchange successfully: the IDD "report
     * records: success" response, or "no records found" -- a successful exchange over a window the
     * pump simply holds nothing in (`history_reader.py` IddRacpResponseCode.NO_RECORDS_FOUND), which
     * must yield an empty list rather than fail the read.
     */
    private fun isReportSuccess(response: ByteArray): Boolean =
        matchesResponse(response, EXPECTED_REPORT_SUCCESS) || matchesResponse(response, REPORT_NO_RECORDS_FOUND)

    private fun matchesResponse(response: ByteArray, expected: ByteArray): Boolean =
        response.size >= expected.size && expected.indices.all { response[it] == expected[it] }

    private fun rangeRequest(firstSeq: Int, lastSeq: Int): ByteArray =
        REQUEST_REPORT_WITHIN_RANGE_PREFIX + MedtronicCodec.u32Le(firstSeq) + MedtronicCodec.u32Le(lastSeq)

    private fun ByteArray.toHex(): String = MedtronicCodec.toHex(this)

    companion object {
        // IDD RACP op codes / operators / filter types (history_reader.py IddRacpOpCode/Operator/FilterType).
        private const val OP_REPORT_RECORDS = 51 // 0x33
        private const val OP_REPORT_NUMBER_OF_RECORDS = 90 // 0x5A
        private const val NUMBER_OF_RECORDS_RESPONSE = 102 // 0x66
        private const val RESPONSE_CODE = 15 // 0x0F
        private const val OPERATOR_NULL = 15 // 0x0F
        private const val OPERATOR_ALL_RECORDS = 51 // 0x33
        private const val OPERATOR_WITHIN_RANGE = 90 // 0x5A
        private const val OPERATOR_LAST_RECORD = 105 // 0x69
        private const val FILTER_SEQUENCE_NUMBER = 15 // 0x0F
        private const val RESPONSE_SUCCESS = 240 // 0xF0
        private const val RESPONSE_NO_RECORDS_FOUND = 6 // 0x06

        /** RACP: report stored records, last record, by sequence number. */
        val REQUEST_REPORT_LAST_RECORD =
            byteArrayOf(OP_REPORT_RECORDS.toByte(), OPERATOR_LAST_RECORD.toByte(), FILTER_SEQUENCE_NUMBER.toByte())

        /** RACP: report the number of stored records, all records, by sequence number. */
        val REQUEST_REPORT_NUMBER_OF_RECORDS =
            byteArrayOf(OP_REPORT_NUMBER_OF_RECORDS.toByte(), OPERATOR_ALL_RECORDS.toByte(), FILTER_SEQUENCE_NUMBER.toByte())

        /** RACP: report stored records within a sequence-number range; followed by min/max u32 LE. */
        val REQUEST_REPORT_WITHIN_RANGE_PREFIX =
            byteArrayOf(OP_REPORT_RECORDS.toByte(), OPERATOR_WITHIN_RANGE.toByte(), FILTER_SEQUENCE_NUMBER.toByte())

        /** Terminating success indication: response-code / null / report-records / success. */
        val EXPECTED_REPORT_SUCCESS =
            byteArrayOf(RESPONSE_CODE.toByte(), OPERATOR_NULL.toByte(), OP_REPORT_RECORDS.toByte(), RESPONSE_SUCCESS.toByte())

        /** Terminating "no records found" indication: a successful exchange over an empty window. */
        val REPORT_NO_RECORDS_FOUND =
            byteArrayOf(RESPONSE_CODE.toByte(), OPERATOR_NULL.toByte(), OP_REPORT_RECORDS.toByte(), RESPONSE_NO_RECORDS_FOUND.toByte())
    }
}
