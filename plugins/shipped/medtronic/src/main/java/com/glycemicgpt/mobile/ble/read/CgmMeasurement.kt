/*
 * CGM Measurement record parser for the Medtronic MiniMed 700-series read-only driver.
 *
 * Ported to Kotlin from OpenMinimed PythonPumpConnector `cgm_measurement.py` (CGMMeasurement),
 * https://github.com/OpenMinimed, GPL-3.0, used with the author's permission. Copyright (C)
 * OpenMinimed contributors: palmarci (Pal Marci), drfubar, Morten Fyhn Amundsen, Stenium; original
 * medtronic-bt-decrypt PoC by @planiitis. GlycemicGPT is itself GPL-3.0, so this is redistributed
 * under the same license.
 *
 * Bluetooth SIG "CGM Measurement" record (GSS section 3.43). The pump SAKE-encrypts this record on
 * the wire; the caller decrypts it (MedtronicSessionReader) before parsing here.
 */
package com.glycemicgpt.mobile.ble.read

/**
 * A decoded CGM Measurement record. Glucose and trend are in **mg/dL** (the 700-series reports
 * mg/dL); [trendMgDlPerMin] is the rate of change. Optional fields are `null`/absent when their
 * presence flag is clear, matching the SIG record's flag-driven layout.
 *
 * TODO(mmol/L): this assumes the 700-series always reports mg/dL. The Bluetooth SIG "CGM Feature"
 * characteristic exposes the device's measurement unit; a real European mmol/L pump sample is needed
 * to confirm it and add a conversion (via the shared 18.0156 factor) here. Deferred -- hardware-blocked.
 * The canonical-mg/dL storage invariant is unaffected because no mmol/L source is parsed yet.
 *
 * Use [parse] to decode a (already-decrypted) record; it throws [MedtronicReadException] on any
 * structural inconsistency rather than returning a half-populated object.
 */
internal data class CgmMeasurement(
    val flags: Int,
    val glucoseMgDl: Double,
    val timeOffsetMinutes: Int,
    val status: Int,
    val trendMgDlPerMin: Double?,
    val quality: Double?,
) {
    companion object {
        // Flag bits (GSS 3.43), low to high.
        private const val FLAG_TREND_PRESENT = 0x01
        private const val FLAG_QUALITY_PRESENT = 0x02
        private const val FLAG_WARNING_PRESENT = 0x20
        private const val FLAG_CAL_TEMP_PRESENT = 0x40
        private const val FLAG_STATUS_PRESENT = 0x80

        // Mandatory prefix: size(1) + flags(1) + glucose SFLOAT(2) + time offset(2).
        private const val MANDATORY_SIZE = 6

        /**
         * Decode a decrypted CGM Measurement record. [useCrc] selects the E2E-CRC-protected layout
         * (the CRC is validated and stripped first); it must come from the CGM Feature's E2E_CRC bit
         * (see [CgmFeature]), never a per-model assumption.
         *
         * @throws MedtronicReadException if the record is too short, the size field disagrees with
         *     the buffer length, the E2E-CRC fails, or trailing bytes remain after the declared
         *     optional fields.
         */
        fun parse(record: ByteArray, useCrc: Boolean): CgmMeasurement {
            val minLength = if (useCrc) MANDATORY_SIZE + MedtronicCodec.CRC_SIZE else MANDATORY_SIZE
            if (record.size < minLength) {
                throw MedtronicReadException(
                    "CGM record too short: need >= $minLength bytes, got ${record.size}",
                )
            }

            // The size field counts the whole record including the CRC, so validate it before the
            // CRC is stripped (matches upstream, which compares against the original length).
            val sizeField = MedtronicCodec.readUIntLe(record, 0, 1)
            if (sizeField != record.size) {
                throw MedtronicReadException(
                    "CGM record length ${record.size} != size field $sizeField",
                )
            }

            var end = record.size
            if (useCrc) {
                if (!MedtronicCodec.checkE2eCrc(record)) {
                    throw MedtronicReadException("CGM record E2E-CRC mismatch")
                }
                end -= MedtronicCodec.CRC_SIZE
            }

            val flags = MedtronicCodec.readUIntLe(record, 1, 1)
            val glucose = MedtronicCodec.decodeMedFloat16(MedtronicCodec.readUIntLe(record, 2, 2))
            val timeOffset = MedtronicCodec.readUIntLe(record, 4, 2)

            // Walk the optional octets in wire order, bounds-checking each so a flag that promises a
            // field the buffer doesn't contain is rejected rather than read out of bounds.
            var offset = MANDATORY_SIZE
            fun consume(n: Int, field: String): Int {
                if (offset + n > end) {
                    throw MedtronicReadException("CGM record missing $field field")
                }
                val value = MedtronicCodec.readUIntLe(record, offset, n)
                offset += n
                return value
            }

            var status = 0
            if (flags and FLAG_STATUS_PRESENT != 0) status = consume(1, "status")
            if (flags and FLAG_CAL_TEMP_PRESENT != 0) consume(1, "cal/temp")
            if (flags and FLAG_WARNING_PRESENT != 0) consume(1, "warning")
            val trend =
                if (flags and FLAG_TREND_PRESENT != 0) {
                    MedtronicCodec.decodeMedFloat16(consume(2, "trend"))
                } else {
                    null
                }
            val quality =
                if (flags and FLAG_QUALITY_PRESENT != 0) {
                    MedtronicCodec.decodeMedFloat16(consume(2, "quality"))
                } else {
                    null
                }

            if (offset != end) {
                throw MedtronicReadException(
                    "CGM record has ${end - offset} trailing byte(s) after declared fields",
                )
            }

            return CgmMeasurement(
                flags = flags,
                glucoseMgDl = glucose,
                timeOffsetMinutes = timeOffset,
                status = status,
                trendMgDlPerMin = trend,
                quality = quality,
            )
        }
    }
}
