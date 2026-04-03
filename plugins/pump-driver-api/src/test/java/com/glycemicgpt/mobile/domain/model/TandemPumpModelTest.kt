package com.glycemicgpt.mobile.domain.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TandemPumpModelTest {

    @Test
    fun `fromAdvertisedName detects X2 from tslim X2 prefix`() {
        val model = TandemPumpModel.fromAdvertisedName("tslim X2 ABC123")
        assertEquals(TandemPumpModel.TSLIM_X2, model)
    }

    @Test
    fun `fromAdvertisedName detects Mobi from Tandem Mobi prefix`() {
        val model = TandemPumpModel.fromAdvertisedName("Tandem Mobi DEF456")
        assertEquals(TandemPumpModel.MOBI, model)
    }

    @Test
    fun `fromAdvertisedName returns UNKNOWN for null`() {
        val model = TandemPumpModel.fromAdvertisedName(null)
        assertEquals(TandemPumpModel.UNKNOWN, model)
    }

    @Test
    fun `fromAdvertisedName returns UNKNOWN for unrecognized name`() {
        val model = TandemPumpModel.fromAdvertisedName("OmniPod 5")
        assertEquals(TandemPumpModel.UNKNOWN, model)
    }

    @Test
    fun `fromAdvertisedName returns UNKNOWN for BleScanner fallback name`() {
        val model = TandemPumpModel.fromAdvertisedName("Tandem Pump")
        assertEquals(TandemPumpModel.UNKNOWN, model)
    }

    @Test
    fun `fromAdvertisedName is case insensitive for X2`() {
        assertEquals(TandemPumpModel.TSLIM_X2, TandemPumpModel.fromAdvertisedName("TSLIM X2 TEST"))
    }

    @Test
    fun `fromAdvertisedName is case insensitive for Mobi`() {
        assertEquals(TandemPumpModel.MOBI, TandemPumpModel.fromAdvertisedName("tandem mobi test"))
    }

    @Test
    fun `fromAdvertisedName returns UNKNOWN for empty string`() {
        assertEquals(TandemPumpModel.UNKNOWN, TandemPumpModel.fromAdvertisedName(""))
    }

    @Test
    fun `hasScreen is true for X2, false for Mobi, null for UNKNOWN`() {
        assertEquals(true, TandemPumpModel.TSLIM_X2.hasScreen)
        assertEquals(false, TandemPumpModel.MOBI.hasScreen)
        assertNull(TandemPumpModel.UNKNOWN.hasScreen)
    }
}
