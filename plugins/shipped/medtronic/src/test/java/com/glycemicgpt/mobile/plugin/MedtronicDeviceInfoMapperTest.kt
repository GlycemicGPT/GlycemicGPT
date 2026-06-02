/*
 * AC1: the MedtronicDeviceInfo -> PumpSettings / PumpHardwareInfo adaptation (string fields carry
 * verbatim; the Long-keyed hardware view extracts numeric ids and preserves the strings as features).
 */
package com.glycemicgpt.mobile.plugin

import com.glycemicgpt.mobile.ble.read.MedtronicDeviceInfo
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MedtronicDeviceInfoMapperTest {

    private fun info(
        model: String = "MMT-1880",
        serial: String = "NG1234567H",
        hw: String = "RevA",
        fw: String = "4.2.1",
        sw: String = "10.5",
        systemId: String = "0011223344556677",
    ) = MedtronicDeviceInfo(model, serial, hw, fw, sw, systemId)

    @Test
    fun `toPumpSettings carries the strings verbatim`() {
        val settings = info().toPumpSettings()
        assertEquals("4.2.1", settings.firmwareVersion)
        assertEquals("NG1234567H", settings.serialNumber)
        assertEquals("MMT-1880", settings.modelNumber)
    }

    @Test
    fun `toPumpHardwareInfo extracts numeric ids and maps revisions`() {
        val hw = info().toPumpHardwareInfo()
        assertEquals(1880L, hw.modelNumber)
        assertEquals(1234567L, hw.serialNumber)
        assertEquals("4.2.1", hw.pumpRev)
        assertEquals("RevA", hw.pcbaRev)
        assertEquals(0L, hw.partNumber)
    }

    @Test
    fun `toPumpHardwareInfo leaves the feature-flag map empty`() {
        // pumpFeatures is a genuine feature-flag map (uploaded as pump_features); it must not be
        // repurposed for identity strings. Identity is carried losslessly by toPumpSettings.
        assertTrue(info().toPumpHardwareInfo().pumpFeatures.isEmpty())
    }

    @Test
    fun `numeric id is zero when an identifier has no digits`() {
        val hw = info(model = "UNKNOWN", serial = "NONE").toPumpHardwareInfo()
        assertEquals(0L, hw.modelNumber)
        assertEquals(0L, hw.serialNumber)
    }

    @Test
    fun `numeric id picks the longest digit run`() {
        // "AB12-3456789" -> longest run 3456789, not 12.
        val hw = info(serial = "AB12-3456789").toPumpHardwareInfo()
        assertEquals(3456789L, hw.serialNumber)
    }
}
