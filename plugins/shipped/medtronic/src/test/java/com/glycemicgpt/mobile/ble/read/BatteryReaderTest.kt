/*
 * AC4: Battery Level read (plain SIG percentage byte, not SAKE-encrypted) into a BatteryStatus, with
 * rejection of an out-of-range or empty value rather than clamping.
 */
package com.glycemicgpt.mobile.ble.read

import com.glycemicgpt.mobile.ble.protocol.MedtronicProtocol
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Test

class BatteryReaderTest {

    private val fixedNow = Instant.ofEpochSecond(1_700_000_000)

    private fun reader(link: FakeGattLink) = BatteryReader(link) { fixedNow }

    @Test
    fun `reads a valid battery percentage`() {
        val link = FakeGattLink()
        link.reads[MedtronicProtocol.BATTERY_LEVEL_UUID] = byteArrayOf(72)

        val status = reader(link).read()

        assertEquals(72, status.percentage)
        assertFalse(status.isCharging)
        assertEquals(fixedNow, status.timestamp)
    }

    @Test
    fun `rejects a percentage above 100`() {
        val link = FakeGattLink()
        link.reads[MedtronicProtocol.BATTERY_LEVEL_UUID] = byteArrayOf(0xFF.toByte())
        assertThrows(MedtronicReadException::class.java) { reader(link).read() }
    }

    @Test
    fun `rejects an empty battery value`() {
        val link = FakeGattLink()
        link.reads[MedtronicProtocol.BATTERY_LEVEL_UUID] = ByteArray(0)
        assertThrows(MedtronicReadException::class.java) { reader(link).read() }
    }
}
