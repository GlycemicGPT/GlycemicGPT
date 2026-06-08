/*
 * IDD status payload parsers for the Medtronic MiniMed 700-series read-only driver.
 *
 * Ported to Kotlin from OpenMinimed PythonPumpConnector `idd/status/pump_status.py` (PumpStatus),
 * `idd/status/iob.py` (InsulinOnBoardData) and `idd/status/active_basal_rate_delivery.py`
 * (ActiveBasalRateDelivery), https://github.com/OpenMinimed, GPL-3.0, used with the author's
 * permission. Copyright (C) OpenMinimed contributors: palmarci (Pal Marci), drfubar, Morten Fyhn
 * Amundsen, Stenium; original medtronic-bt-decrypt PoC by @planiitis. GlycemicGPT is itself GPL-3.0,
 * so this is redistributed under the same license.
 *
 * Each value is SAKE-encrypted on the wire; the caller (MedtronicSessionReader) decrypts before
 * parsing here. All amounts are medfloat32 IU. See medtronic-ble-reverse-engineering.md Sec. 8.
 */
package com.glycemicgpt.mobile.ble.read

/** Pump therapy control state (`pump_status.py` TherapyControlState). */
enum class TherapyControlState(val raw: Int) {
    UNDETERMINED(0x0F),
    STOP(0x33),
    PAUSE(0x3C),
    RUN(0x55),
    UNKNOWN(-1),
    ;

    companion object {
        fun from(raw: Int): TherapyControlState = entries.firstOrNull { it.raw == raw } ?: UNKNOWN
    }
}

/** Pump operational state (`pump_status.py` OperationalState). */
enum class OperationalState(val raw: Int) {
    UNDETERMINED(0x0F),
    OFF(0x33),
    STANDBY(0x3C),
    PREPARING(0x55),
    PRIMING(0x5A),
    WAITING(0x66),
    READY(0x96),
    UNKNOWN(-1),
    ;

    companion object {
        fun from(raw: Int): OperationalState = entries.firstOrNull { it.raw == raw } ?: UNKNOWN
    }
}

/** Sensor message / annunciation state surfaced in the IDD status (`pump_status.py` SensorMessageState). */
enum class SensorMessageState(val raw: Int) {
    NO_MESSAGE(0x00),
    WAIT_TO_CALIBRATE(0x01),
    DO_NOT_CALIBRATE(0x02),
    CALIBRATION_REQUIRED(0x03),
    CALIBRATING(0x04),
    SEARCHING_FOR_SENSOR_SIGNAL(0x05),
    NO_SENSOR_SIGNAL(0x06),
    CHANGE_SENSOR(0x07),
    WARM_UP(0x08),
    SG_BELOW_LOWER_LIMIT(0x09),
    SG_ABOVE_UPPER_LIMIT(0x0A),
    GST_BATTERY_DEPLETED(0x0B),
    SENSOR_CONNECTED(0x0C),
    WAITING_WARM_UP(0x0D),
    NO_PAIRED_SENSOR(0x0E),
    UNKNOWN(-1),
    ;

    companion object {
        fun from(raw: Int): SensorMessageState = entries.firstOrNull { it.raw == raw } ?: UNKNOWN
    }
}

/**
 * Decoded IDD Status record (`0x102`): therapy/operational state, reservoir units, and sensor state.
 *
 * @property reservoirRemainingIu reservoir units remaining (IU).
 * @property reservoirAttached IDD status flag bit 0 (reservoir attached).
 * @property sensorConnectivityFlags raw sensor-connectivity flag byte (bit0 on, bit1 paired, ...).
 */
data class IddStatusRecord(
    val therapyControlState: TherapyControlState,
    val operationalState: OperationalState,
    val reservoirRemainingIu: Double,
    val reservoirAttached: Boolean,
    val sensorConnectivityFlags: Int,
    val sensorMessageState: SensorMessageState,
) {
    companion object {
        private const val BODY_SIZE = 9
        private const val RESERVOIR_ATTACHED_BIT = 1 shl 0

        /**
         * Parse a decrypted IDD Status value. When [useE2e] the trailing E2E-Counter (1) + E2E-CRC (2)
         * are validated and stripped first (read [IddFeatures.e2eProtectionEnabled] per pump rather
         * than assuming, the upstream caveat).
         *
         * @throws MedtronicReadException on a length mismatch or failed E2E-CRC.
         */
        fun parse(decrypted: ByteArray, useE2e: Boolean): IddStatusRecord {
            val body = stripIddE2e(decrypted, useE2e)
            if (body.size != BODY_SIZE) {
                throw MedtronicReadException("IDD Status length ${body.size} != expected $BODY_SIZE")
            }
            val therapy = TherapyControlState.from(MedtronicCodec.readUIntLe(body, 0, 1))
            val operational = OperationalState.from(MedtronicCodec.readUIntLe(body, 1, 1))
            val reservoir = MedtronicCodec.decodeMedFloat32(MedtronicCodec.readULongLe(body, 2, 4))
            val flags = MedtronicCodec.readUIntLe(body, 6, 1)
            val sensorConnectivity = MedtronicCodec.readUIntLe(body, 7, 1)
            val sensorMessage = SensorMessageState.from(MedtronicCodec.readUIntLe(body, 8, 1))
            return IddStatusRecord(
                therapyControlState = therapy,
                operationalState = operational,
                reservoirRemainingIu = reservoir,
                reservoirAttached = flags and RESERVOIR_ATTACHED_BIT != 0,
                sensorConnectivityFlags = sensorConnectivity,
                sensorMessageState = sensorMessage,
            )
        }
    }
}

/**
 * Decoded Insulin-On-Board response (SRCP opcode `0x03F3` -> response `0x03FC`).
 *
 * ⚠️ **PROVISIONAL.** Upstream marks IOB parsing "not tested" (`iob.py`); this is implemented
 * faithfully but must be validated against a real pump before it is trusted. `TODO(48.A2)`.
 *
 * @property insulinOnBoardIu active insulin on board (IU, medfloat32).
 */
data class IddInsulinOnBoard(
    val insulinOnBoardIu: Double,
    val remainingDurationMin: Int?,
) {
    companion object {
        private const val RESPONSE_OPCODE = 0x03FC
        private const val REMAINING_DURATION_PRESENT = 1 shl 0
        private const val IOB_PARTIAL_STATUS_PRESENT = 1 shl 1
        private const val MIN_BODY_SIZE = 7 // opcode(2) + flags(1) + IOB f32(4)

        /** @throws MedtronicReadException on a length mismatch, wrong opcode, or failed E2E-CRC. */
        fun parse(decrypted: ByteArray, useE2e: Boolean): IddInsulinOnBoard {
            val body = stripIddE2e(decrypted, useE2e)
            if (body.size < MIN_BODY_SIZE) {
                throw MedtronicReadException("IDD IOB too short: need >= $MIN_BODY_SIZE bytes, got ${body.size}")
            }
            val opcode = MedtronicCodec.readUIntLe(body, 0, 2)
            if (opcode != RESPONSE_OPCODE) {
                throw MedtronicReadException("IDD IOB wrong opcode 0x%04x, wanted 0x%04x".format(opcode, RESPONSE_OPCODE))
            }
            val flags = MedtronicCodec.readUIntLe(body, 2, 1)
            val iob = MedtronicCodec.decodeMedFloat32(MedtronicCodec.readULongLe(body, 3, 4))
            var offset = MIN_BODY_SIZE
            fun consume(n: Int, field: String): Int {
                if (offset + n > body.size) throw MedtronicReadException("IDD IOB missing $field field")
                return MedtronicCodec.readUIntLe(body, offset, n).also { offset += n }
            }
            val remainingDuration = if (flags and REMAINING_DURATION_PRESENT != 0) consume(2, "remaining-duration") else null
            if (flags and IOB_PARTIAL_STATUS_PRESENT != 0) {
                consume(2, "iob-partial-duration")
                consume(2, "iob-partial-remaining")
            }
            if (offset != body.size) {
                throw MedtronicReadException("IDD IOB has ${body.size - offset} trailing byte(s) after declared fields")
            }
            return IddInsulinOnBoard(insulinOnBoardIu = iob, remainingDurationMin = remainingDuration)
        }
    }
}

/** Basal delivery context (`active_basal_rate_delivery.py` BasalDeliveryContext). */
enum class BasalDeliveryContext(val raw: Int) {
    UNDETERMINED(0x0F),
    DEVICE_BASED(0x33),
    REMOTE_CONTROL(0x3C),
    AP_CONTROLLER(0x55),
    UNKNOWN(-1),
    ;

    companion object {
        fun from(raw: Int): BasalDeliveryContext = entries.firstOrNull { it.raw == raw } ?: UNKNOWN
    }
}

/**
 * Decoded Active Basal Rate Delivery response (SRCP opcode `0x0365` -> response `0x036A`).
 *
 * @property rateIuPerHour the active basal rate currently being delivered (IU/h, medfloat32).
 * @property basalDeliveryContext present only when the pump reports it; [BasalDeliveryContext.AP_CONTROLLER]
 *     means the closed-loop algorithm (SmartGuard) is driving the rate (770G/780G).
 */
data class IddActiveBasalRate(
    val rateIuPerHour: Double,
    val templateNumber: Int,
    val basalDeliveryContext: BasalDeliveryContext?,
) {
    companion object {
        private const val RESPONSE_OPCODE = 0x036A
        private const val TBR_PRESENT = 1 shl 0
        private const val TBR_TEMPLATE_NUMBER_PRESENT = 1 shl 1
        private const val BASAL_DELIVERY_CONTEXT_PRESENT = 1 shl 2
        private const val MIN_BODY_SIZE = 8 // opcode(2) + flags(1) + template(1) + rate f32(4)

        /** @throws MedtronicReadException on a length mismatch, wrong opcode, or failed E2E-CRC. */
        fun parse(decrypted: ByteArray, useE2e: Boolean): IddActiveBasalRate {
            val body = stripIddE2e(decrypted, useE2e)
            if (body.size < MIN_BODY_SIZE) {
                throw MedtronicReadException("IDD basal too short: need >= $MIN_BODY_SIZE bytes, got ${body.size}")
            }
            val opcode = MedtronicCodec.readUIntLe(body, 0, 2)
            if (opcode != RESPONSE_OPCODE) {
                throw MedtronicReadException("IDD basal wrong opcode 0x%04x, wanted 0x%04x".format(opcode, RESPONSE_OPCODE))
            }
            val flags = MedtronicCodec.readUIntLe(body, 2, 1)
            val template = MedtronicCodec.readUIntLe(body, 3, 1)
            val rate = MedtronicCodec.decodeMedFloat32(MedtronicCodec.readULongLe(body, 4, 4))
            var offset = MIN_BODY_SIZE
            fun consume(n: Int, field: String): Int {
                if (offset + n > body.size) throw MedtronicReadException("IDD basal missing $field field")
                return MedtronicCodec.readUIntLe(body, offset, n).also { offset += n }
            }
            // TBR block (type, adjustment f32, programmed dur, remaining dur) -- read past it; the active
            // delivered rate is the mandatory field above, which already reflects any TBR adjustment.
            if (flags and TBR_PRESENT != 0) {
                consume(1, "tbr-type")
                consume(4, "tbr-adjustment")
                consume(2, "tbr-duration-programmed")
                consume(2, "tbr-duration-remaining")
            }
            if (flags and TBR_TEMPLATE_NUMBER_PRESENT != 0) consume(1, "tbr-template-number")
            val context =
                if (flags and BASAL_DELIVERY_CONTEXT_PRESENT != 0) {
                    BasalDeliveryContext.from(consume(1, "basal-delivery-context"))
                } else {
                    null
                }
            if (offset != body.size) {
                throw MedtronicReadException("IDD basal has ${body.size - offset} trailing byte(s) after declared fields")
            }
            return IddActiveBasalRate(rateIuPerHour = rate, templateNumber = template, basalDeliveryContext = context)
        }
    }
}

/**
 * Validate and strip the optional Medtronic E2E trailer (E2E-Counter byte + 2-byte E2E-CRC) the IDD
 * service appends when [useE2e]. The CRC covers everything up to and including the counter; on a
 * match the counter and CRC are dropped, leaving the bare record body. Shared by every IDD payload
 * parser (matches the `if self.use_e2e:` block repeated across the upstream IDD parsers).
 *
 * @throws MedtronicReadException if the value is too short to hold the trailer or the CRC mismatches.
 */
internal fun stripIddE2e(value: ByteArray, useE2e: Boolean): ByteArray {
    if (!useE2e) return value
    // counter(1) + crc(2)
    val trailer = 1 + MedtronicCodec.CRC_SIZE
    if (value.size < trailer) {
        throw MedtronicReadException("IDD record too short for E2E trailer: ${value.size} bytes")
    }
    if (!MedtronicCodec.checkE2eCrc(value)) {
        throw MedtronicReadException("IDD record E2E-CRC mismatch")
    }
    return value.copyOf(value.size - trailer)
}
