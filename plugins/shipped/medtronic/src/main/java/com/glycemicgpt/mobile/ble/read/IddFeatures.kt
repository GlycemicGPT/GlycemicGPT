/*
 * IDD Features characteristic parser for the Medtronic MiniMed 700-series read-only driver.
 *
 * Ported to Kotlin from OpenMinimed PythonPumpConnector `idd/features/pump_features.py` (PumpFeatures)
 * and `idd/features/reader.py` (IDDFeaturesReader), https://github.com/OpenMinimed, GPL-3.0, used
 * with the author's permission. Copyright (C) OpenMinimed contributors: palmarci (Pal Marci),
 * drfubar, Morten Fyhn Amundsen, Stenium; original medtronic-bt-decrypt PoC by @planiitis.
 * GlycemicGPT is itself GPL-3.0, so this is redistributed under the same license.
 */
package com.glycemicgpt.mobile.ble.read

/**
 * Decoded IDD Features characteristic (`0x104`, SAKE-encrypted; the caller decrypts before parsing).
 *
 * Two things this driver acts on: [e2eProtectionEnabled] (whether the IDD Status/SRCP/history records
 * carry the Medtronic E2E-Counter + E2E-CRC trailer -- read per pump rather than the upstream
 * 780G-hardcoded assumption that it is off), and [model] (the SmartGuard capability tier inferred from
 * the feature bits, see [MedtronicPumpModel]).
 *
 * @property insulinConcentration insulin concentration in IU/mL (medfloat16).
 * @property featureFlags the variable-width feature bit word (extension bytes folded in).
 */
data class IddFeatures(
    val insulinConcentration: Double,
    val featureFlags: Long,
    val e2eProtectionEnabled: Boolean,
    val model: MedtronicPumpModel,
) {
    companion object {
        /** Mandatory prefix: e2e-crc(2) + e2e-counter(1) + concentration SFLOAT(2) + flags(3). */
        private const val MANDATORY_SIZE = 8

        /** E2E Protection Supported feature bit (bit 0): when set the IDD service uses E2E framing. */
        private const val E2E_PROTECTION_SUPPORTED = 1L shl 0

        /** Feature Extension bit (bit 23): another flags byte follows, folded in at shift 24. */
        private const val FEATURE_EXTENSION = 1L shl 23

        private const val FLAGS_FIELD_SIZE = 3
        private const val EXTENSION_CONTINUE_BIT = 0x80

        /**
         * Decode the decrypted IDD Features value.
         *
         * @throws MedtronicReadException if the value is shorter than the mandatory prefix or a
         *     promised feature-extension byte is missing.
         */
        fun parse(decrypted: ByteArray): IddFeatures {
            if (decrypted.size < MANDATORY_SIZE) {
                throw MedtronicReadException(
                    "IDD Features too short: need >= $MANDATORY_SIZE bytes, got ${decrypted.size}",
                )
            }
            // bytes 0-1 e2e-crc, byte 2 e2e-counter -- only meaningful when E2E is enabled (the bit
            // below); upstream asserts they are 0xffff/0 because the 780G leaves E2E off. We read the
            // bit and don't hard-assert, so a model that does enable E2E is not misparsed here.
            val concentration = MedtronicCodec.decodeMedFloat16(MedtronicCodec.readUIntLe(decrypted, 3, 2))
            var flags = MedtronicCodec.readUIntLe(decrypted, 5, FLAGS_FIELD_SIZE).toLong()

            var offset = MANDATORY_SIZE
            fun nextExtensionByte(): Int {
                if (offset >= decrypted.size) {
                    throw MedtronicReadException("IDD Features missing a promised feature-extension byte")
                }
                return MedtronicCodec.readUIntLe(decrypted, offset++, 1)
            }
            if (flags and FEATURE_EXTENSION != 0L) {
                var shift = 24
                var ext = nextExtensionByte()
                flags = flags or (ext.toLong() shl shift)
                while (ext and EXTENSION_CONTINUE_BIT != 0) {
                    shift += 8
                    ext = nextExtensionByte()
                    flags = flags or (ext.toLong() shl shift)
                }
            }

            return IddFeatures(
                insulinConcentration = concentration,
                featureFlags = flags,
                e2eProtectionEnabled = flags and E2E_PROTECTION_SUPPORTED != 0L,
                model = MedtronicPumpModel.fromFeatureFlags(flags),
            )
        }
    }
}
