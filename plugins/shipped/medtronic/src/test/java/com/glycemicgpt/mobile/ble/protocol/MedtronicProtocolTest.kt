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
        assertEquals(
            "0000fe82-0000-1000-8000-00805f9b34fb",
            MedtronicProtocol.SAKE_CHARACTERISTIC_UUID.toString(),
        )
        // Vendor base carries the Medtronic node id (...-009132591325).
        assertEquals(
            "00000100-0000-1000-8000-009132591325",
            MedtronicProtocol.IDD_SERVICE_UUID.toString(),
        )
        assertEquals(
            "00000300-0000-1000-8000-009132591325",
            MedtronicProtocol.HAT_SERVICE_UUID.toString(),
        )
        // The two bases must not collapse: the same short code maps to distinct UUIDs.
        assertNotEquals(MedtronicProtocol.sigUuid(0x100), MedtronicProtocol.vendorUuid(0x100))
    }
}
