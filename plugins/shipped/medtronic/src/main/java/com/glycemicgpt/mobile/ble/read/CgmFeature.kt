/*
 * CGM Feature characteristic parser for the Medtronic MiniMed 700-series read-only driver.
 *
 * Ported to Kotlin from OpenMinimed PythonPumpConnector `cgm_features.py` (CGMFeatures),
 * https://github.com/OpenMinimed, GPL-3.0, used with the author's permission. Copyright (C)
 * OpenMinimed contributors: palmarci (Pal Marci), drfubar, Morten Fyhn Amundsen, Stenium; original
 * medtronic-bt-decrypt PoC by @planiitis. GlycemicGPT is itself GPL-3.0, so this is redistributed
 * under the same license.
 *
 * Bluetooth SIG "CGM Feature" characteristic (GSS section 3.42), read from 0x2AA8.
 */
package com.glycemicgpt.mobile.ble.read

/**
 * Decoded CGM Feature characteristic. The single field this driver acts on is [e2eCrcEnabled] (the
 * E2E_CRC feature bit), which governs whether CGM Measurement records carry a trailing E2E-CRC.
 *
 * Reading this flag per pump is the fix for the upstream 780G hard-code: 680G / 770G must not be
 * assumed to use the CRC (medtronic-ble-reverse-engineering.md Sec. 9).
 */
internal data class CgmFeature(
    val featureBits: Int,
    val e2eCrcEnabled: Boolean,
) {
    companion object {
        /** E2E_CRC feature bit (1 << 12) in the 24-bit feature field. */
        private const val E2E_CRC_BIT = 1 shl 12

        /** feature field (3 bytes LE) + type/sample-location (1 byte) + E2E-CRC (2 bytes). */
        private const val EXPECTED_LENGTH = 6
        private const val FEATURE_FIELD_SIZE = 3

        /** Sentinel in the CRC field meaning "E2E-safety unsupported" (the chicken-and-egg workaround). */
        private const val CRC_UNSUPPORTED = 0xFFFF

        /**
         * Decode the 6-byte CGM Feature value.
         *
         * The spec's chicken-and-egg workaround: the flag that says whether E2E-safety is supported
         * lives inside the otherwise CRC-protected packet, so the CRC field is *always* present and
         * set to 0xffff when unsupported. We therefore validate the CRC only when the field isn't the
         * 0xffff sentinel, then take [e2eCrcEnabled] from the feature bit itself.
         *
         * (Upstream's `cgm_features.py` compares `data[:-2]` instead of the trailing two bytes to the
         * 0xffff sentinel, which never matches and so always validates the CRC; we compare the actual
         * CRC field, per the documented intent.)
         *
         * @throws MedtronicReadException on an unexpected length or a CRC mismatch.
         */
        fun parse(value: ByteArray): CgmFeature {
            if (value.size != EXPECTED_LENGTH) {
                throw MedtronicReadException(
                    "CGM Feature length ${value.size} != expected $EXPECTED_LENGTH",
                )
            }
            val crcField = MedtronicCodec.readUIntLe(value, EXPECTED_LENGTH - MedtronicCodec.CRC_SIZE, MedtronicCodec.CRC_SIZE)
            if (crcField != CRC_UNSUPPORTED && !MedtronicCodec.checkE2eCrc(value)) {
                throw MedtronicReadException("CGM Feature E2E-CRC mismatch")
            }
            val featureBits = MedtronicCodec.readUIntLe(value, 0, FEATURE_FIELD_SIZE)
            return CgmFeature(
                featureBits = featureBits,
                e2eCrcEnabled = featureBits and E2E_CRC_BIT != 0,
            )
        }
    }
}
