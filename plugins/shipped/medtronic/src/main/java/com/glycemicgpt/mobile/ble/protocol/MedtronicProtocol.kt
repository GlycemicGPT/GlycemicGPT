/*
 * BLE protocol constant inventory for the Medtronic MiniMed 700-series read-only driver.
 *
 * Derived from OpenMinimed (https://github.com/OpenMinimed), GPL-3.0, used with the author's
 * permission: the advertising contract from PythonPumpConnector / JavaPumpConnector and the GATT
 * service/characteristic map from uuids.py. Copyright (C) OpenMinimed contributors: palmarci
 * (Pal Marci), drfubar, Morten Fyhn Amundsen, Stenium; original medtronic-bt-decrypt PoC by
 * @planiitis. GlycemicGPT is itself GPL-3.0, so this is redistributed under the same license.
 *
 * This is an INVENTORY only -- service/characteristic UUIDs and the advertising contract. There
 * are no parsers here; the read layer (CGM/IDD/HAT decoders) lands in Milestone C, ported from
 * PythonPumpConnector. Values flagged DESK in medtronic-ble-reverse-engineering.md still need live
 * confirmation against a real pump.
 */
package com.glycemicgpt.mobile.ble.protocol

import android.os.ParcelUuid
import java.util.UUID

/**
 * Medtronic MiniMed 700-series (680G / 770G / 780G) BLE constants.
 *
 * The phone is the BLE peripheral (GATT server) and the pump is the central -- the inverted
 * topology vs Tandem (see medtronic-ble-reverse-engineering.md Sec. 3). These constants describe
 * what the phone advertises and the GATT table it must expose / the pump exposes back.
 */
object MedtronicProtocol {

    // -- UUID bases --------------------------------------------------------

    // Bluetooth SIG base: a 16-bit code XXXX expands to 0000XXXX-0000-1000-8000-00805f9b34fb.
    private const val SIG_BASE_SUFFIX = "-0000-1000-8000-00805f9b34fb"

    // Medtronic vendor-specific 128-bit base (node ...-009132591325, per OpenMinimed uuids.py):
    // a 16-bit code XXXX expands to 0000XXXX-0000-1000-8000-009132591325.
    private const val MEDTRONIC_BASE_SUFFIX = "-0000-1000-8000-009132591325"

    private fun uuidFor(short16: Int, baseSuffix: String): UUID {
        val hex = (short16 and 0xFFFF).toString(16).padStart(4, '0')
        return UUID.fromString("0000$hex$baseSuffix")
    }

    /** Build a 128-bit UUID for a 16-bit SIG short code. */
    fun sigUuid(short16: Int): UUID = uuidFor(short16, SIG_BASE_SUFFIX)

    /** Build a 128-bit UUID for a 16-bit Medtronic vendor short code. */
    fun vendorUuid(short16: Int): UUID = uuidFor(short16, MEDTRONIC_BASE_SUFFIX)

    // -- Advertising contract (what the pump scans for) --------------------
    // medtronic-ble-reverse-engineering.md Sec. 3.

    /** Medtronic Bluetooth company identifier used in the advertisement's manufacturer data. */
    const val COMPANY_ID = 0x01F9

    /**
     * The pump only connects to advertisers whose local name matches this pattern, e.g.
     * "Mobile 123456". Advertisers that don't fit are rejected.
     */
    val LOCAL_NAME_PATTERN = Regex("Mobile .{0,7}")

    /** Local-name prefix the advertised name is built from (prefix + suffix). */
    const val LOCAL_NAME_PREFIX = "Mobile "

    /** 16-bit service-class UUID advertised for a first-time pairing. This is the SAKE service. */
    const val SAKE_SERVICE_FIRST_PAIR_16 = 0xFE82

    /**
     * 16-bit service-class UUID advertised when reconnecting to an already-paired pump -- an
     * adjacent Medtronic-assigned UUID one below the first-pair service (0xFE82 vs 0xFE81; they
     * differ in the low two bits). DESK: carry into Milestone B reconnect logic.
     */
    const val SAKE_SERVICE_RECONNECT_16 = 0xFE81

    val SAKE_SERVICE_FIRST_PAIR_UUID: UUID = sigUuid(SAKE_SERVICE_FIRST_PAIR_16)
    val SAKE_SERVICE_RECONNECT_UUID: UUID = sigUuid(SAKE_SERVICE_RECONNECT_16)

    // Lazy so loading this constant table on a plain JVM (unit tests) does not construct the
    // Android ParcelUuid; the advertiser (Milestone B2) touches these on-device.
    val SAKE_SERVICE_FIRST_PAIR_PARCEL: ParcelUuid by lazy { ParcelUuid(SAKE_SERVICE_FIRST_PAIR_UUID) }
    val SAKE_SERVICE_RECONNECT_PARCEL: ParcelUuid by lazy { ParcelUuid(SAKE_SERVICE_RECONNECT_UUID) }

    /**
     * Pairing security: BLE Just Works, IO capability NoInputNoOutput (io-cap 3). The pump requests
     * the MITM flag but does not support LE Secure Connections, so the stack must fall back to Just
     * Works. LE-only / connectable / BR-EDR off. App-layer authentication is the SAKE handshake, not
     * BLE pairing. DESK.
     */
    const val IO_CAPABILITY_NO_INPUT_NO_OUTPUT = 3

    /**
     * Build the manufacturer-specific data payload for the advertisement: 0x00 + name + 0x00 (name
     * is the full "Mobile NNNNNN" local name). Sec. 3. This is ONLY the payload; the [COMPANY_ID]
     * (0x01F9) is passed separately to AdvertiseData.addManufacturerData(companyId, payload) by the
     * advertiser (Milestone B2), so it is intentionally not part of the returned bytes.
     */
    fun manufacturerData(localName: String): ByteArray {
        val nameBytes = localName.toByteArray(Charsets.US_ASCII)
        return ByteArray(nameBytes.size + 2).also { out ->
            // out[0] and the trailing byte stay 0x00 from allocation; copy the name into the middle.
            nameBytes.copyInto(out, destinationOffset = 1)
        }
    }

    // -- GATT service / characteristic map ---------------------------------
    // medtronic-ble-reverse-engineering.md Sec. 8. All read-only for our purposes (subscribe/read);
    // no write/control characteristics are exposed by design.

    /** SAKE authentication service: 0xFE82 first-pair / 0xFE81 reconnect. Char NOTIFY + WRITE. */
    val SAKE_CHARACTERISTIC_UUID: UUID = sigUuid(SAKE_SERVICE_FIRST_PAIR_16)

    /** Device Information service (0x180A): manufacturer/model/serial/hw/fw/sw, system + PnP id. */
    val DEVICE_INFO_SERVICE_UUID: UUID = sigUuid(0x180A)
    val MANUFACTURER_NAME_UUID: UUID = sigUuid(0x2A29)
    val MODEL_NUMBER_UUID: UUID = sigUuid(0x2A24)
    val SERIAL_NUMBER_UUID: UUID = sigUuid(0x2A25)
    val FIRMWARE_REVISION_UUID: UUID = sigUuid(0x2A26)
    val HARDWARE_REVISION_UUID: UUID = sigUuid(0x2A27)
    val SOFTWARE_REVISION_UUID: UUID = sigUuid(0x2A28)
    val SYSTEM_ID_UUID: UUID = sigUuid(0x2A23)
    val PNP_ID_UUID: UUID = sigUuid(0x2A50)

    /** Battery service (0x180F): Battery Level 0x2A19. */
    val BATTERY_SERVICE_UUID: UUID = sigUuid(0x180F)
    val BATTERY_LEVEL_UUID: UUID = sigUuid(0x2A19)

    /** Continuous Glucose (CGM) service (0x181F). */
    val CGM_SERVICE_UUID: UUID = sigUuid(0x181F)
    val CGM_MEASUREMENT_UUID: UUID = sigUuid(0x2AA7)
    val CGM_FEATURE_UUID: UUID = sigUuid(0x2AA8)
    val CGM_SOCP_UUID: UUID = sigUuid(0x2AAC)

    /** Insulin Delivery (IDD) service (0x100, vendor base): reservoir, therapy state, IOB, basal. */
    val IDD_SERVICE_UUID: UUID = vendorUuid(0x100)
    val IDD_STATUS_UUID: UUID = vendorUuid(0x102)
    val IDD_FEATURES_UUID: UUID = vendorUuid(0x104)
    val IDD_SRCP_UUID: UUID = vendorUuid(0x105)
    val IDD_HISTORY_DATA_UUID: UUID = vendorUuid(0x108)

    /** History and Trace (HAT) service (0x300, vendor base): event log to bolus/basal/sensor/alarm. */
    val HAT_SERVICE_UUID: UUID = vendorUuid(0x300)
    val HAT_SLICE_RECORD_UUID: UUID = vendorUuid(0x350)
    val HAT_RTMCP_UUID: UUID = vendorUuid(0x360)
    val HAT_RMCPSE_UUID: UUID = vendorUuid(0x370)

    /** Certificate Management (CM) service (0x600, vendor base). Not needed for read-only data. */
    val CM_SERVICE_UUID: UUID = vendorUuid(0x600)
    val CM_CP_UUID: UUID = vendorUuid(0x601)
    val CM_DATA_UUID: UUID = vendorUuid(0x602)

    /** Record Access Control Point (0x2A52): shared by CGM, IDD and HAT for paged reads. */
    val RACP_UUID: UUID = sigUuid(0x2A52)

    /** Client Characteristic Configuration Descriptor. */
    val CCCD_UUID: UUID = sigUuid(0x2902)
}
