/*
 * Application-layer PDU fragmentation for the Medtronic MiniMed 700-series read-only driver.
 *
 * Honors the 23-byte ATT MTU / 20-byte PDU constraint documented in
 * `medtronic-ble-reverse-engineering.md` Sec. 6 (carried from OpenMinimed's Linux client, GPL-3.0):
 * the pump advertises MTU 184 but only honors 23-byte PDUs, and the official Android app never
 * negotiates the MTU up. We never call requestMtu(); every notification/write payload must stay
 * <= 20 bytes (23 - 3-byte ATT header). SAKE handshake messages are already exactly 20 bytes and
 * pass through unfragmented.
 */
package com.glycemicgpt.mobile.ble.protocol

/**
 * Splits oversized payloads into <= 20-byte PDUs and concatenates them back.
 *
 * This enforces only the transport PDU-size cap. The higher-layer Medtronic framing (RACP / SOCP
 * length fields, record paging) is added by the Milestone C readers on top of this; here a fragment
 * is just a raw slice and [reassemble] is the exact inverse of [fragment].
 */
object PduFramer {

    /** Default ATT MTU the driver operates at -- never negotiated up (Sec. 6). */
    const val DEFAULT_MTU = 23

    /** ATT protocol header overhead subtracted from the MTU to get the usable payload size. */
    const val ATT_HEADER_SIZE = 3

    /** Maximum bytes per PDU at the default MTU: 23 - 3 = 20. */
    const val MAX_PDU_SIZE = DEFAULT_MTU - ATT_HEADER_SIZE

    /**
     * Fragment [payload] into chunks no larger than [maxPduSize]. A payload that already fits in a
     * single PDU is returned as one chunk (a copy). An empty payload yields a single empty chunk so
     * the boundary is still transmitted.
     *
     * @param maxPduSize the per-PDU cap; must be in `1..`[MAX_PDU_SIZE] so a caller cannot
     *     accidentally request a chunk the pump would drop.
     */
    fun fragment(payload: ByteArray, maxPduSize: Int = MAX_PDU_SIZE): List<ByteArray> {
        require(maxPduSize in 1..MAX_PDU_SIZE) {
            "maxPduSize $maxPduSize must be in 1..$MAX_PDU_SIZE"
        }
        if (payload.size <= maxPduSize) {
            return listOf(payload.copyOf())
        }
        val chunks = ArrayList<ByteArray>((payload.size + maxPduSize - 1) / maxPduSize)
        var offset = 0
        while (offset < payload.size) {
            val end = minOf(offset + maxPduSize, payload.size)
            chunks.add(payload.copyOfRange(offset, end))
            offset = end
        }
        return chunks
    }

    /**
     * Concatenate [fragments] back into the original payload (the exact inverse of [fragment]). This
     * is the stateless list-based inverse; the incremental, notification-driven reassembly the
     * connection manager / readers need (accumulate PDUs until a length/terminator is reached, as in
     * Tandem's PacketAssembler) is layered on top of this in Milestone B2/C.
     */
    fun reassemble(fragments: List<ByteArray>): ByteArray {
        val total = fragments.sumOf { it.size }
        val out = ByteArray(total)
        var offset = 0
        for (fragment in fragments) {
            fragment.copyInto(out, destinationOffset = offset)
            offset += fragment.size
        }
        return out
    }
}
