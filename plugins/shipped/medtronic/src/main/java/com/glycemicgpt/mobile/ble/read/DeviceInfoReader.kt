/*
 * Device Information reader for the Medtronic MiniMed 700-series read-only driver.
 *
 * GlycemicGPT code (GPL-3.0). The characteristic set and the trailing-terminator handling are ported
 * from OpenMinimed PythonPumpConnector `device_info.py` (DeviceInfo), GPL-3.0, used with the
 * author's permission. Copyright (C) OpenMinimed contributors: palmarci (Pal Marci), drfubar,
 * Morten Fyhn Amundsen, Stenium; original medtronic-bt-decrypt PoC by @planiitis. GlycemicGPT is
 * itself GPL-3.0.
 *
 * Device Information Service (0x180A) characteristics are standard Bluetooth SIG strings and are NOT
 * SAKE-encrypted -- plain GATT reads, the simplest proof of the read plumbing.
 */
package com.glycemicgpt.mobile.ble.read

import com.glycemicgpt.mobile.ble.protocol.MedtronicProtocol

/**
 * Identifying hardware/firmware strings from the pump's Device Information Service.
 *
 * Medtronic's DIS values are alphanumeric strings (e.g. model "MMT-1880", serial "NG..."), so they
 * are kept as strings here rather than forced into the Tandem-shaped, `Long`-keyed
 * [com.glycemicgpt.mobile.domain.model.PumpHardwareInfo]. Adapting this native shape onto the shared
 * capability surface is a Milestone C3 concern (the capability delegates that wrap these readers).
 */
data class MedtronicDeviceInfo(
    val modelNumber: String,
    val serialNumber: String,
    val hardwareRevision: String,
    val firmwareRevision: String,
    val softwareRevision: String,
    val systemId: String,
)

/** Reads the pump's Device Information Service into a [MedtronicDeviceInfo]. */
class DeviceInfoReader(private val link: MedtronicGattLink) {

    /**
     * Read all Device Information characteristics. String fields are UTF-8 with any trailing NUL
     * terminator trimmed (upstream strips a fixed terminator byte; trimming only NULs avoids
     * truncating a value that isn't null-terminated). The 8-byte System ID is rendered as hex.
     */
    fun read(): MedtronicDeviceInfo =
        MedtronicDeviceInfo(
            modelNumber = readString(MedtronicProtocol.MODEL_NUMBER_UUID),
            serialNumber = readString(MedtronicProtocol.SERIAL_NUMBER_UUID),
            hardwareRevision = readString(MedtronicProtocol.HARDWARE_REVISION_UUID),
            firmwareRevision = readString(MedtronicProtocol.FIRMWARE_REVISION_UUID),
            softwareRevision = readString(MedtronicProtocol.SOFTWARE_REVISION_UUID),
            systemId = readHex(MedtronicProtocol.SYSTEM_ID_UUID),
        )

    private fun readString(characteristic: java.util.UUID): String =
        link.read(characteristic).dropLastWhile { it.toInt() == 0 }.toByteArray().toString(Charsets.UTF_8)

    private fun readHex(characteristic: java.util.UUID): String =
        link.read(characteristic).joinToString("") { "%02x".format(it) }
}
