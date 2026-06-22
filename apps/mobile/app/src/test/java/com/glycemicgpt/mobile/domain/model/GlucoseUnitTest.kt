package com.glycemicgpt.mobile.domain.model

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Parsing + default behaviour for [GlucoseUnit]. [fromName] is exactly the logic the
 * [com.glycemicgpt.mobile.data.local.AppSettingsStore] cache getter delegates to, so these
 * cover the "default mg/dL, fall back on unparseable" guarantee without an Android context.
 */
class GlucoseUnitTest {

    @Test
    fun `wire values mirror the backend enum`() {
        assertEquals("mgdl", GlucoseUnit.MGDL.wireValue)
        assertEquals("mmol", GlucoseUnit.MMOL.wireValue)
    }

    @Test
    fun `fromWire parses backend json values`() {
        assertEquals(GlucoseUnit.MGDL, GlucoseUnit.fromWire("mgdl"))
        assertEquals(GlucoseUnit.MMOL, GlucoseUnit.fromWire("mmol"))
        assertEquals(GlucoseUnit.MMOL, GlucoseUnit.fromWire("MMOL"))
    }

    @Test
    fun `fromWire falls back to mgdl on unknown or null`() {
        assertEquals(GlucoseUnit.MGDL, GlucoseUnit.fromWire(null))
        assertEquals(GlucoseUnit.MGDL, GlucoseUnit.fromWire(""))
        assertEquals(GlucoseUnit.MGDL, GlucoseUnit.fromWire("gibberish"))
    }

    @Test
    fun `fromName parses stored enum names`() {
        assertEquals(GlucoseUnit.MGDL, GlucoseUnit.fromName("MGDL"))
        assertEquals(GlucoseUnit.MMOL, GlucoseUnit.fromName("MMOL"))
    }

    @Test
    fun `fromName falls back to mgdl on unknown or null`() {
        assertEquals(GlucoseUnit.MGDL, GlucoseUnit.fromName(null))
        assertEquals(GlucoseUnit.MGDL, GlucoseUnit.fromName("mmol")) // wire value is not a valid name
        assertEquals(GlucoseUnit.MGDL, GlucoseUnit.fromName("nonsense"))
    }
}
