package com.glycemicgpt.mobile.ble.protocol

import android.os.ParcelUuid
import java.util.UUID

/**
 * Tandem BLE protocol constants.
 *
 * UUIDs and message format derived from studying jwoglom/pumpX2 (MIT licensed).
 * We do not depend on pumpX2 at runtime.
 */
object TandemProtocol {

    // -- GATT Service UUIDs ------------------------------------------------

    val PUMP_SERVICE_UUID: UUID =
        UUID.fromString("0000fdfb-0000-1000-8000-00805f9b34fb")

    val PUMP_SERVICE_PARCEL: ParcelUuid = ParcelUuid(PUMP_SERVICE_UUID)

    val DIS_SERVICE_UUID: UUID =
        UUID.fromString("0000180A-0000-1000-8000-00805f9b34fb")

    // -- GATT Characteristic UUIDs -----------------------------------------

    /** Unsigned status reads (IoB, basal, battery, reservoir, etc.) */
    val CURRENT_STATUS_UUID: UUID =
        UUID.fromString("7B83FFF6-9F77-4E5C-8064-AAE2C24838B9")

    /** Qualifying events / alerts */
    val QUALIFYING_EVENTS_UUID: UUID =
        UUID.fromString("7B83FFF7-9F77-4E5C-8064-AAE2C24838B9")

    /** History log streaming */
    val HISTORY_LOG_UUID: UUID =
        UUID.fromString("7B83FFF8-9F77-4E5C-8064-AAE2C24838B9")

    /** Authentication handshake messages */
    val AUTHORIZATION_UUID: UUID =
        UUID.fromString("7B83FFF9-9F77-4E5C-8064-AAE2C24838B9")

    /** Signed control messages */
    val CONTROL_UUID: UUID =
        UUID.fromString("7B83FFFC-9F77-4E5C-8064-AAE2C24838B9")

    /** Signed control stream */
    val CONTROL_STREAM_UUID: UUID =
        UUID.fromString("7B83FFFD-9F77-4E5C-8064-AAE2C24838B9")

    /** Client Characteristic Configuration Descriptor */
    val CCCD_UUID: UUID =
        UUID.fromString("00002902-0000-1000-8000-00805F9B34FB")

    // -- Device Information Service characteristics ------------------------

    val MANUFACTURER_NAME_UUID: UUID =
        UUID.fromString("00002A29-0000-1000-8000-00805f9b34fb")

    val MODEL_NUMBER_UUID: UUID =
        UUID.fromString("00002A24-0000-1000-8000-00805f9b34fb")

    val SERIAL_NUMBER_UUID: UUID =
        UUID.fromString("00002a25-0000-1000-8000-00805f9b34fb")

    val SOFTWARE_REV_UUID: UUID =
        UUID.fromString("00002a28-0000-1000-8000-00805f9b34fb")

    // -- All characteristics that need notification subscription -----------

    val NOTIFICATION_CHARACTERISTICS: List<UUID> = listOf(
        CURRENT_STATUS_UUID,
        QUALIFYING_EVENTS_UUID,
        HISTORY_LOG_UUID,
        AUTHORIZATION_UUID,
        CONTROL_UUID,
        CONTROL_STREAM_UUID,
    )

    // -- Read-only status request opcodes ----------------------------------
    // Tandem response opcode = request opcode + 1.
    // Opcodes verified against jwoglom/pumpX2 source.

    const val OPCODE_CONTROL_IQ_IOB_REQ = 108      // ControlIQIOBRequest
    const val OPCODE_CONTROL_IQ_IOB_RESP = 109      // ControlIQIOBResponse (17 bytes)
    const val OPCODE_CURRENT_BASAL_STATUS_REQ = 40  // CurrentBasalStatusRequest
    const val OPCODE_CURRENT_BASAL_STATUS_RESP = 41 // CurrentBasalStatusResponse (9 bytes)
    // Note: value 36/37 overlap with JPAKE_2 on AUTHORIZATION characteristic.
    // No conflict -- status requests route to CURRENT_STATUS_UUID.
    const val OPCODE_INSULIN_STATUS_REQ = 36        // InsulinStatusRequest
    const val OPCODE_INSULIN_STATUS_RESP = 37       // InsulinStatusResponse (4 bytes)
    const val OPCODE_CURRENT_BATTERY_V1_REQ = 52    // CurrentBatteryV1Request (2 bytes resp)
    const val OPCODE_CURRENT_BATTERY_V1_RESP = 53
    const val OPCODE_CURRENT_BATTERY_V2_REQ = 144   // CurrentBatteryV2Request (11 bytes resp, fw v7.7+)
    const val OPCODE_CURRENT_BATTERY_V2_RESP = 145
    const val OPCODE_LAST_BOLUS_STATUS_REQ = 48     // LastBolusStatusRequest (17-byte resp)
    const val OPCODE_LAST_BOLUS_STATUS_RESP = 49    // LastBolusStatusResponse
    const val OPCODE_PUMP_FEATURES_V1_REQ = 78        // PumpFeaturesV1Request (8-byte bitmask resp)
    const val OPCODE_PUMP_FEATURES_V1_RESP = 79
    const val OPCODE_PUMP_SETTINGS_REQ = 82          // PumpSettingsRequest (was 90 -- wrong)
    const val OPCODE_PUMP_SETTINGS_RESP = 83
    // Note: value 34/35 overlap with JPAKE_1B on AUTHORIZATION characteristic.
    // No conflict -- status requests route to CURRENT_STATUS_UUID.
    const val OPCODE_CGM_EGV_REQ = 34               // CurrentEGVGuiDataRequest
    const val OPCODE_CGM_EGV_RESP = 35              // CurrentEGVGuiDataResponse (8 bytes)
    const val OPCODE_HOME_SCREEN_MIRROR_REQ = 56    // HomeScreenMirrorRequest
    const val OPCODE_HOME_SCREEN_MIRROR_RESP = 57   // HomeScreenMirrorResponse (9 bytes: trend icons, CIQ mode)

    /** Default timeout for a status read request (milliseconds). */
    const val STATUS_READ_TIMEOUT_MS = 5000L

    /** Timeout for history log fetch requests (longer due to multi-packet responses). */
    const val HISTORY_LOG_TIMEOUT_MS = 10_000L

    // -- V1 Authentication opcodes (firmware < v7.7) -------------------------

    const val OPCODE_CENTRAL_CHALLENGE_REQ = 16
    const val OPCODE_CENTRAL_CHALLENGE_RESP = 17
    const val OPCODE_PUMP_CHALLENGE_REQ = 18
    const val OPCODE_PUMP_CHALLENGE_RESP = 19

    // -- JPAKE Authentication opcodes (firmware v7.7+, 6-digit code) --------

    const val OPCODE_JPAKE_1A_REQ = 32
    const val OPCODE_JPAKE_1A_RESP = 33
    const val OPCODE_JPAKE_1B_REQ = 34
    const val OPCODE_JPAKE_1B_RESP = 35
    const val OPCODE_JPAKE_2_REQ = 36
    const val OPCODE_JPAKE_2_RESP = 37
    const val OPCODE_JPAKE_3_SESSION_KEY_REQ = 38
    const val OPCODE_JPAKE_3_SESSION_KEY_RESP = 39
    const val OPCODE_JPAKE_4_KEY_CONFIRM_REQ = 40
    // Note: value 41 also used by OPCODE_INSULIN_STATUS_REQ on CURRENT_STATUS
    // characteristic. No conflict because opcodes are disambiguated by characteristic UUID.
    const val OPCODE_JPAKE_4_KEY_CONFIRM_RESP = 41

    // -- Post-auth baseline opcodes ----------------------------------------
    // Note: opcode 32/33 overlap with JPAKE_1A but are on CURRENT_STATUS characteristic,
    // not AUTHORIZATION. The pump disambiguates by characteristic.

    const val OPCODE_API_VERSION_REQ = 32
    const val OPCODE_API_VERSION_RESP = 33
    const val OPCODE_PUMP_VERSION_REQ = 84           // PumpVersionRequest (was 78 -- wrong)
    const val OPCODE_PUMP_VERSION_RESP = 85
    const val OPCODE_TIME_SINCE_RESET_REQ = 54       // TimeSinceResetRequest (was 80 -- wrong)
    const val OPCODE_TIME_SINCE_RESET_RESP = 55

    // -- History log / hardware info opcodes --------------------------------

    const val OPCODE_HISTORY_LOG_STATUS_REQ = 58     // HistoryLogStatusRequest (was LOG_ENTRY_SEQ 26 -- wrong)
    const val OPCODE_HISTORY_LOG_STATUS_RESP = 59
    const val OPCODE_HISTORY_LOG_REQ = 60             // HistoryLogRequest (5-byte cargo: uint32 startLog + byte count)
    const val OPCODE_HISTORY_LOG_RESP = 61
    const val OPCODE_PUMP_GLOBALS_REQ = 86            // PumpGlobalsRequest (was 88 -- wrong)
    const val OPCODE_PUMP_GLOBALS_RESP = 87

    // -- Connection parameters ---------------------------------------------

    /** Minimum MTU for Tandem long packets */
    const val REQUIRED_MTU = 185

    /** Max chunk size for current status / auth characteristics */
    const val CHUNK_SIZE_SHORT = 18

    /** Max chunk size for control characteristics */
    const val CHUNK_SIZE_LONG = 40

    /** Map an opcode to a human-readable name for debug logging. */
    fun opcodeName(opcode: Int): String = when (opcode) {
        OPCODE_CONTROL_IQ_IOB_REQ -> "IoB_REQ"
        OPCODE_CONTROL_IQ_IOB_RESP -> "IoB_RESP"
        OPCODE_CURRENT_BASAL_STATUS_REQ -> "Basal_REQ"
        OPCODE_CURRENT_BASAL_STATUS_RESP -> "Basal_RESP"
        OPCODE_INSULIN_STATUS_REQ -> "Insulin_REQ"
        OPCODE_INSULIN_STATUS_RESP -> "Insulin_RESP"
        OPCODE_CURRENT_BATTERY_V1_REQ -> "BatteryV1_REQ"
        OPCODE_CURRENT_BATTERY_V1_RESP -> "BatteryV1_RESP"
        OPCODE_CURRENT_BATTERY_V2_REQ -> "BatteryV2_REQ"
        OPCODE_CURRENT_BATTERY_V2_RESP -> "BatteryV2_RESP"
        OPCODE_LAST_BOLUS_STATUS_REQ -> "LastBolus_REQ"
        OPCODE_LAST_BOLUS_STATUS_RESP -> "LastBolus_RESP"
        OPCODE_PUMP_FEATURES_V1_REQ -> "PumpFeaturesV1_REQ"
        OPCODE_PUMP_FEATURES_V1_RESP -> "PumpFeaturesV1_RESP"
        OPCODE_PUMP_SETTINGS_REQ -> "PumpSettings_REQ"
        OPCODE_PUMP_SETTINGS_RESP -> "PumpSettings_RESP"
        OPCODE_CGM_EGV_REQ -> "CGM_EGV_REQ"
        OPCODE_CGM_EGV_RESP -> "CGM_EGV_RESP"
        OPCODE_HOME_SCREEN_MIRROR_REQ -> "HomeScreenMirror_REQ"
        OPCODE_HOME_SCREEN_MIRROR_RESP -> "HomeScreenMirror_RESP"
        OPCODE_CENTRAL_CHALLENGE_REQ -> "V1Auth_CentralChallenge_REQ"
        OPCODE_CENTRAL_CHALLENGE_RESP -> "V1Auth_CentralChallenge_RESP"
        OPCODE_PUMP_CHALLENGE_REQ -> "V1Auth_PumpChallenge_REQ"
        OPCODE_PUMP_CHALLENGE_RESP -> "V1Auth_PumpChallenge_RESP"
        OPCODE_JPAKE_1A_REQ -> "JPAKE_1A_REQ"
        OPCODE_JPAKE_1A_RESP -> "JPAKE_1A_RESP"
        OPCODE_JPAKE_1B_REQ -> "JPAKE_1B_REQ"
        OPCODE_JPAKE_1B_RESP -> "JPAKE_1B_RESP"
        OPCODE_JPAKE_2_REQ -> "JPAKE_2_REQ"
        OPCODE_JPAKE_2_RESP -> "JPAKE_2_RESP"
        OPCODE_JPAKE_3_SESSION_KEY_REQ -> "JPAKE_3_KEY_REQ"
        OPCODE_JPAKE_3_SESSION_KEY_RESP -> "JPAKE_3_KEY_RESP"
        OPCODE_JPAKE_4_KEY_CONFIRM_REQ -> "JPAKE_4_CONFIRM_REQ"
        OPCODE_JPAKE_4_KEY_CONFIRM_RESP -> "JPAKE_4_CONFIRM_RESP"
        OPCODE_HISTORY_LOG_STATUS_REQ -> "HistoryLogStatus_REQ"
        OPCODE_HISTORY_LOG_STATUS_RESP -> "HistoryLogStatus_RESP"
        OPCODE_HISTORY_LOG_REQ -> "HistoryLog_REQ"
        OPCODE_HISTORY_LOG_RESP -> "HistoryLog_RESP"
        OPCODE_PUMP_GLOBALS_REQ -> "PumpGlobals_REQ"
        OPCODE_PUMP_GLOBALS_RESP -> "PumpGlobals_RESP"
        OPCODE_API_VERSION_REQ -> "ApiVersion_REQ"
        OPCODE_API_VERSION_RESP -> "ApiVersion_RESP"
        OPCODE_PUMP_VERSION_REQ -> "PumpVersion_REQ"
        OPCODE_PUMP_VERSION_RESP -> "PumpVersion_RESP"
        OPCODE_TIME_SINCE_RESET_REQ -> "TimeSinceReset_REQ"
        OPCODE_TIME_SINCE_RESET_RESP -> "TimeSinceReset_RESP"
        else -> "Unknown_0x${opcode.toString(16).padStart(2, '0')}"
    }
}
