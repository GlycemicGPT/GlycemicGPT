package com.glycemicgpt.mobile.ble.protocol

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MedtronicProtocolTest {

    @Test
    fun `local-name pattern matches the advertised Mobile name and rejects others`() {
        assertTrue(MedtronicProtocol.LOCAL_NAME_PATTERN.matches("Mobile 123456"))
        assertTrue(MedtronicProtocol.LOCAL_NAME_PATTERN.matches("Mobile "))
        assertTrue(MedtronicProtocol.LOCAL_NAME_PATTERN.matches("Mobile 7654321"))
        assertFalse(MedtronicProtocol.LOCAL_NAME_PATTERN.matches("Mobile 12345678")) // suffix > 7
        assertFalse(MedtronicProtocol.LOCAL_NAME_PATTERN.matches("Phone 123"))
        assertFalse(MedtronicProtocol.LOCAL_NAME_PATTERN.matches("mobile 123"))
    }

    @Test
    fun `manufacturer data wraps the local name with leading and trailing zero bytes`() {
        val name = "Mobile 123456"
        val data = MedtronicProtocol.manufacturerData(name)
        assertEquals(name.length + 2, data.size)
        assertEquals(0x00.toByte(), data.first())
        assertEquals(0x00.toByte(), data.last())
        assertEquals(name, String(data.copyOfRange(1, data.size - 1), Charsets.US_ASCII))
    }

    @Test
    fun `the reconnect service UUID is the documented adjacent Medtronic member UUID`() {
        // 0xFE82 (first pair) and 0xFE81 (reconnect) are adjacent Medtronic-assigned 16-bit UUIDs;
        // they differ in the low two bits (0xFE82 xor 0xFE81 == 0x03).
        assertEquals(0xFE82, MedtronicProtocol.SAKE_SERVICE_FIRST_PAIR_16)
        assertEquals(0xFE81, MedtronicProtocol.SAKE_SERVICE_RECONNECT_16)
        assertEquals(
            0x03,
            MedtronicProtocol.SAKE_SERVICE_FIRST_PAIR_16 xor
                MedtronicProtocol.SAKE_SERVICE_RECONNECT_16,
        )
    }

    @Test
    fun `company id is the Medtronic identifier`() {
        assertEquals(0x01F9, MedtronicProtocol.COMPANY_ID)
    }

    @Test
    fun `sig and vendor UUIDs expand their 16-bit codes against the right base`() {
        assertEquals(
            "0000180a-0000-1000-8000-00805f9b34fb",
            MedtronicProtocol.sigUuid(0x180A).toString(),
        )
        // Vendor base carries the Medtronic node id (...-009132591325) with variant field 0000, not
        // the SIG 8000 (issue #844, per OpenMinimed uuids.py / JavaPumpConnector).
        assertEquals(
            "00000100-0000-1000-0000-009132591325",
            MedtronicProtocol.IDD_SERVICE_UUID.toString(),
        )
        assertEquals(
            "00000300-0000-1000-0000-009132591325",
            MedtronicProtocol.HAT_SERVICE_UUID.toString(),
        )
        // The two bases must not collapse: the same short code maps to distinct UUIDs.
        assertNotEquals(MedtronicProtocol.sigUuid(0x100), MedtronicProtocol.vendorUuid(0x100))
    }

    @Test
    fun `issue 844 - GATT identities the phone exposes match the validated JavaPumpConnector`() {
        // The phone is the BLE peripheral; a real 780G only pairs when the GATT table it discovers
        // matches what the official app exposes. These values are pinned against OpenMinimed's
        // JavaPumpConnector BlePeripheralDevice, which paired on the reporter's hardware. Three
        // identities are subtle and previously shipped wrong (issue #844), so assert them directly.

        // 1. The Device Information service container is the proprietary vendor 0x0900, NOT SIG 0x180A.
        assertEquals(
            "00000900-0000-1000-0000-009132591325",
            MedtronicProtocol.DEVICE_INFO_SERVICE_UUID.toString(),
        )
        // 2. The SAKE *service* is advertised and registered on the SIG base (0xFE82)...
        assertEquals(
            "0000fe82-0000-1000-8000-00805f9b34fb",
            MedtronicProtocol.SAKE_SERVICE_FIRST_PAIR_UUID.toString(),
        )
        // 3. ...but the SAKE *characteristic* inside it lives on the vendor base (same 0xFE82 code).
        assertEquals(
            "0000fe82-0000-1000-0000-009132591325",
            MedtronicProtocol.SAKE_CHARACTERISTIC_UUID.toString(),
        )
        // The service/characteristic split is the crux: same short code, different base.
        assertNotEquals(
            MedtronicProtocol.SAKE_SERVICE_FIRST_PAIR_UUID,
            MedtronicProtocol.SAKE_CHARACTERISTIC_UUID,
        )
    }
}
