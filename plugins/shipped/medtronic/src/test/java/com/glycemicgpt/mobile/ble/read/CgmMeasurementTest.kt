/*
 * Tests for CgmMeasurement parsing against OpenMinimed-captured CGM Measurement vectors
 * (cgm_measurement.py), plus the E2E-CRC present/absent layouts and structural rejections.
 */
package com.glycemicgpt.mobile.ble.read

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class CgmMeasurementTest {

    @Test
    fun `parses the captured 249 mgdl rising vector with E2E-CRC`() {
        val m = CgmMeasurement.parse(hex("0ec3f900f40b000074e00a00e0f1"), useCrc = true)
        assertEquals(249.0, m.glucoseMgDl, 1e-9)
        assertEquals(3060, m.timeOffsetMinutes)
        assertEquals(1.16, m.trendMgDlPerMin!!, 1e-9)
        assertEquals(10.0, m.quality!!, 1e-9)
    }

    @Test
    fun `parses the captured 141 mgdl flat vector with E2E-CRC`() {
        val m = CgmMeasurement.parse(hex("0ec38d00e803000010e00a00d9af"), useCrc = true)
        assertEquals(141.0, m.glucoseMgDl, 1e-9)
        assertEquals(1000, m.timeOffsetMinutes)
        assertEquals(0.16, m.trendMgDlPerMin!!, 1e-9)
    }

    @Test
    fun `parses a record without E2E-CRC when the feature flag is off`() {
        // Same fields as the captured vector, CRC stripped and the size field adjusted to 12.
        val m = CgmMeasurement.parse(hex("0cc3f900f40b000074e00a00"), useCrc = false)
        assertEquals(249.0, m.glucoseMgDl, 1e-9)
        assertEquals(1.16, m.trendMgDlPerMin!!, 1e-9)
    }

    @Test
    fun `absent trend flag yields null trend`() {
        // flags 0x00 -> no optional octets; size 6, glucose 100 (0x0064), offset 0.
        val m = CgmMeasurement.parse(hex("060064000000"), useCrc = false)
        assertEquals(100.0, m.glucoseMgDl, 1e-9)
        assertNull(m.trendMgDlPerMin)
        assertNull(m.quality)
    }

    @Test
    fun `rejects a record shorter than the mandatory prefix`() {
        assertThrows(MedtronicReadException::class.java) {
            CgmMeasurement.parse(hex("0ec3f9"), useCrc = true)
        }
    }

    @Test
    fun `rejects a size field that disagrees with the buffer length`() {
        assertThrows(MedtronicReadException::class.java) {
            CgmMeasurement.parse(hex("0fc3f900f40b000074e00a00e0f1"), useCrc = true)
        }
    }

    @Test
    fun `rejects a failed E2E-CRC`() {
        assertThrows(MedtronicReadException::class.java) {
            CgmMeasurement.parse(hex("0ec3f900f40b000074e00a00e0f0"), useCrc = true)
        }
    }
}
