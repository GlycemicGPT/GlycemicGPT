/*
 * Low-level value decoding for the Medtronic MiniMed 700-series read-only driver.
 *
 * Ported to Kotlin from OpenMinimed PythonPumpConnector (https://github.com/OpenMinimed),
 * GPL-3.0, used with the author's permission: the IEEE-11073 SFLOAT/FLOAT decode, the sign-extend,
 * and the little-endian field consumers from `parse_utils.py` (ParseUtils) and the E2E-CRC /
 * medfloat helpers from `value_converter.py` (ValueConverter). Copyright (C) OpenMinimed
 * contributors: palmarci (Pal Marci), drfubar, Morten Fyhn Amundsen, Stenium; original
 * medtronic-bt-decrypt PoC by @planiitis. GlycemicGPT is itself GPL-3.0, so this is redistributed
 * under the same license.
 *
 * See medtronic-ble-reverse-engineering.md Sec. 8-9.
 */
package com.glycemicgpt.mobile.ble.read

/**
 * Pure byte-level decoders shared by the Medtronic CGM / device-info parsers: little-endian
 * integers, the IEEE-11073 16-bit SFLOAT ("medfloat16") used by the CGM Measurement record, and the
 * E2E-CRC (CRC-16/CCITT-FALSE) that guards CGM packets.
 *
 * Stateless and side-effect free so the parsers stay unit-testable against captured frames.
 */
internal object MedtronicCodec {

    /**
     * Read [n] bytes of [data] starting at [offset] as a little-endian unsigned integer.
     *
     * Bounded to 1..3 bytes: a signed [Int] cannot represent a full unsigned 32-bit value, so a
     * 4-byte field with the top bit set would read back negative and silently violate the unsigned
     * contract. The 4-byte (uint32) fields appear only in the history records (48.C2); add a
     * `Long`-returning reader there rather than widening this one.
     */
    fun readUIntLe(data: ByteArray, offset: Int, n: Int): Int {
        require(n in 1..3) { "n must be in 1..3 (Int cannot hold a full uint32), was $n" }
        require(offset >= 0 && offset + n <= data.size) {
            "range [$offset, ${offset + n}) out of bounds for ${data.size} bytes"
        }
        var value = 0
        for (i in 0 until n) {
            value = value or ((data[offset + i].toInt() and 0xFF) shl (8 * i))
        }
        return value
    }

    /**
     * Read [n] bytes of [data] starting at [offset] as a little-endian unsigned integer, widened into
     * a [Long]. Bounded to 1..4 bytes: the IDD/history records carry unsigned 32-bit fields (record
     * sequence number, bolus start-time offset, annunciation timestamp) that overflow a signed [Int];
     * [readUIntLe] stays the right tool for the 1..3-byte fields. Mirrors `ParseUtils.consume_u32`.
     */
    fun readULongLe(data: ByteArray, offset: Int, n: Int): Long {
        require(n in 1..4) { "n must be in 1..4, was $n" }
        require(offset >= 0 && offset + n <= data.size) {
            "range [$offset, ${offset + n}) out of bounds for ${data.size} bytes"
        }
        var value = 0L
        for (i in 0 until n) {
            value = value or ((data[offset + i].toLong() and 0xFF) shl (8 * i))
        }
        return value
    }

    /** Lower-case hex of [data], for diagnostic/error messages. */
    fun toHex(data: ByteArray): String = data.joinToString("") { "%02x".format(it) }

    /** Encode [value] as a 4-byte little-endian unsigned 32-bit field (the RACP sequence operands). */
    fun u32Le(value: Int): ByteArray =
        byteArrayOf(
            (value and 0xFF).toByte(),
            ((value ushr 8) and 0xFF).toByte(),
            ((value ushr 16) and 0xFF).toByte(),
            ((value ushr 24) and 0xFF).toByte(),
        )

    /**
     * Sign-extend the low [bits] of [value] to a signed [Int]. Mirrors `ValueConverter.sign_extend`;
     * used for the signed time-offset fields in the history records (`consume_i16`).
     */
    fun signExtend(value: Int, bits: Int): Int {
        require(bits in 1..32) { "bits must be in 1..32, was $bits" }
        // A full-width Int needs no extension, and `1 shl 32` would wrap (Kotlin masks the shift count
        // to the low 5 bits, so `1 shl 32 == 1`) and corrupt the result.
        if (bits == 32) return value
        val signBit = 1 shl (bits - 1)
        return if (value and signBit != 0) value - (1 shl bits) else value
    }

    /**
     * Decode a 32-bit IEEE-11073 FLOAT ("medfloat32"): an 8-bit signed exponent in the high byte and
     * a 24-bit signed mantissa, valued as `mantissa * 10^exponent`. Mirrors
     * `ValueConverter.decode_medfloat32`; used for the insulin amounts (reservoir, IOB, basal rate,
     * bolus units) the IDD/history records carry in IU.
     *
     * Takes the raw value as a [Long] (from [readULongLe] with n=4) so the unsigned 32-bit field is
     * not misread as a negative [Int]. Computed with [Math.pow] rather than the [decodeMedFloat16]
     * lookup table because the signed-byte exponent spans -128..127 and these fields are read only a
     * few times per status read, not per CGM sample.
     *
     * Unlike [decodeMedFloat16] this does not special-case the IEEE-11073 reserved/NaN/Inf mantissa
     * codes (upstream's `decode_medfloat32` does not either, and the 32-bit reserved codes differ).
     * A reserved/garbled insulin field therefore decodes to a bogus finite number or a non-finite
     * value; callers gate it with `isFinite()` + a physiological range check and reject it, so a
     * sentinel never surfaces as a real reservoir/IOB/basal/bolus amount.
     */
    fun decodeMedFloat32(raw: Long): Double {
        var exponent = ((raw ushr 24) and 0xFF).toInt()
        var mantissa = (raw and 0x00FFFFFF).toInt()
        if (exponent and 0x80 != 0) exponent -= 0x100
        if (mantissa and 0x800000 != 0) mantissa -= 0x1000000
        return mantissa.toDouble() * Math.pow(10.0, exponent.toDouble())
    }

    /**
     * Decode a 16-bit IEEE-11073 SFLOAT: a 4-bit signed exponent in the high nibble and a 12-bit
     * signed mantissa, valued as `mantissa * 10^exponent`. Mirrors `ValueConverter.decode_medfloat16`.
     * For CGM glucose the exponent is 0, so the value is the integer mantissa in mg/dL; the trend
     * field uses a small negative exponent (e.g. mantissa 116, exponent -2 -> 1.16 mg/dL/min).
     *
     * Computed as `mantissa * 10^exponent` via a precomputed power-of-ten table. Upstream
     * `value_converter.py` instead parses `float(f"{m}e{e}")` to minimize floating-point drift; the
     * difference is immaterial here because glucose is rounded to an Int and trend is only
     * magnitude-bucketed into arrows.
     *
     * The reserved IEEE-11073 SFLOAT mantissa codes are returned as non-finite Doubles
     * (NaN / +-Infinity) rather than decoded as ordinary numbers, so callers reject them instead of
     * surfacing a "no value" sentinel (e.g. 0x07FF) as a real glucose or trend. Upstream
     * `value_converter.py` does not special-case these; we do, because the trend field is only
     * magnitude-bucketed and would otherwise turn a sentinel into a bogus arrow.
     */
    fun decodeMedFloat16(raw: Int): Double {
        when (raw and 0x0FFF) {
            SFLOAT_NAN, SFLOAT_NRES, SFLOAT_RESERVED -> return Double.NaN
            SFLOAT_POSITIVE_INFINITY -> return Double.POSITIVE_INFINITY
            SFLOAT_NEGATIVE_INFINITY -> return Double.NEGATIVE_INFINITY
        }
        var exponent = (raw and 0xF000) shr 12
        var mantissa = raw and 0x0FFF
        if (exponent and 0x8 != 0) exponent -= 0x10
        if (mantissa and 0x800 != 0) mantissa -= 0x1000
        return mantissa.toDouble() * POW10[exponent + EXPONENT_BIAS]
    }

    /**
     * CRC-16/CCITT-FALSE over [data]: width 16, polynomial 0x1021, init 0xffff, no input/output
     * reflection, zero final XOR. Mirrors `ValueConverter.e2e_crc`.
     */
    fun e2eCrc(data: ByteArray, length: Int = data.size): Int {
        var crc = 0xFFFF
        for (i in 0 until length) {
            crc = crc xor ((data[i].toInt() and 0xFF) shl 8)
            repeat(8) {
                crc = if (crc and 0x8000 != 0) (crc shl 1) xor 0x1021 else crc shl 1
                crc = crc and 0xFFFF
            }
        }
        return crc
    }

    /**
     * Verify the trailing 2-byte little-endian E2E-CRC of a packet: the CRC is computed over every
     * byte except the last two and compared to those two. Mirrors `ValueConverter.check_crc`.
     */
    fun checkE2eCrc(message: ByteArray): Boolean {
        if (message.size < CRC_SIZE) return false
        val received = readUIntLe(message, message.size - CRC_SIZE, CRC_SIZE)
        return e2eCrc(message, message.size - CRC_SIZE) == received
    }

    /** Number of trailing bytes holding the little-endian E2E-CRC. */
    const val CRC_SIZE = 2

    // Exponents seen on the wire span a single signed nibble (-8..7); precompute the powers of ten
    // so decoding does no floating-point exponentiation per field.
    private const val EXPONENT_BIAS = 8
    private val POW10 = DoubleArray(16) { Math.pow(10.0, (it - EXPONENT_BIAS).toDouble()) }

    // Reserved IEEE-11073 SFLOAT mantissa codes (12-bit field, exponent-independent).
    private const val SFLOAT_POSITIVE_INFINITY = 0x07FE
    private const val SFLOAT_NAN = 0x07FF
    private const val SFLOAT_NRES = 0x0800
    private const val SFLOAT_RESERVED = 0x0801
    private const val SFLOAT_NEGATIVE_INFINITY = 0x0802
}
