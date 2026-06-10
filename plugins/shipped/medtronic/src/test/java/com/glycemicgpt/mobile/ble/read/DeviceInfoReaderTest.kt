/*
 * AC4: Device Information Service reads (plain SIG strings, not SAKE-encrypted) into a
 * MedtronicDeviceInfo, including trailing-NUL trimming and the hex System ID.
 */
package com.glycemicgpt.mobile.ble.read

import com.glycemicgpt.mobile.ble.protocol.MedtronicProtocol
import org.junit.Assert.assertEquals
import org.junit.Test

class DeviceInfoReaderTest {

    @Test
    fun `reads device information strings and the system id`() {
        val link = FakeGattLink()
        link.reads[MedtronicProtocol.MODEL_NUMBER_UUID] = "MMT-1880".toByteArray()
        // A NUL-terminated value, as some firmware reports DIS strings.
        link.reads[MedtronicProtocol.SERIAL_NUMBER_UUID] = "NG1234567H".toByteArray() + 0x00
        link.reads[MedtronicProtocol.HARDWARE_REVISION_UUID] = "1.0".toByteArray()
        link.reads[MedtronicProtocol.FIRMWARE_REVISION_UUID] = "8.0.1".toByteArray()
        link.reads[MedtronicProtocol.SOFTWARE_REVISION_UUID] = "BLE 4.2".toByteArray()
        link.reads[MedtronicProtocol.SYSTEM_ID_UUID] = byteArrayOf(0x01, 0x02, 0x03, 0xAB.toByte())

        val info = DeviceInfoReader(link).read()

        assertEquals("MMT-1880", info.modelNumber)
        assertEquals("NG1234567H", info.serialNumber)
        assertEquals("1.0", info.hardwareRevision)
        assertEquals("8.0.1", info.firmwareRevision)
        assertEquals("BLE 4.2", info.softwareRevision)
        assertEquals("010203ab", info.systemId)
    }
}
