package com.glycemicgpt.weardevice.util

import org.junit.Assert.assertEquals
import org.junit.Test

class GlucoseUnitTest {

    @Test
    fun `fromWire parses the canonical tokens`() {
        assertEquals(GlucoseUnit.MGDL, GlucoseUnit.fromWire("mgdl"))
        assertEquals(GlucoseUnit.MMOL, GlucoseUnit.fromWire("mmol"))
    }

    @Test
    fun `fromWire is case-insensitive`() {
        assertEquals(GlucoseUnit.MMOL, GlucoseUnit.fromWire("MMOL"))
        assertEquals(GlucoseUnit.MGDL, GlucoseUnit.fromWire("MgDl"))
    }

    @Test
    fun `fromWire falls back to MGDL for null, empty, or unknown`() {
        assertEquals(GlucoseUnit.MGDL, GlucoseUnit.fromWire(null))
        assertEquals(GlucoseUnit.MGDL, GlucoseUnit.fromWire(""))
        assertEquals(GlucoseUnit.MGDL, GlucoseUnit.fromWire("bogus"))
    }

    @Test
    fun `wireValue round-trips through fromWire`() {
        for (unit in GlucoseUnit.entries) {
            assertEquals(unit, GlucoseUnit.fromWire(unit.wireValue))
        }
    }
}
