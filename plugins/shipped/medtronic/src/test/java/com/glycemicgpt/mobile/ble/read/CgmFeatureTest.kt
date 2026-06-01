/*
 * Tests for CgmFeature: the E2E_CRC feature bit drives whether measurements carry a CRC (read per
 * pump, never hard-coded for 780G), and the 0xffff sentinel marks E2E-safety unsupported.
 */
package com.glycemicgpt.mobile.ble.read

import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class CgmFeatureTest {

    @Test
    fun `reads E2E_CRC enabled from the captured feature vector`() {
        // cgm_features.py __main__ vector: feature bits include bit 12 (E2E_CRC), CRC field present.
        assertTrue(CgmFeature.parse(hex("009001591404")).e2eCrcEnabled)
    }

    @Test
    fun `treats the 0xffff CRC sentinel as E2E unsupported and skips validation`() {
        // feature bits 0x000091 (no bit 12), CRC field = 0xffff -> unsupported, CRC not validated.
        val feature = CgmFeature.parse(hex("910000" + "14" + "ffff"))
        assertFalse(feature.e2eCrcEnabled)
    }

    @Test
    fun `rejects a wrong-length feature value`() {
        assertThrows(MedtronicReadException::class.java) { CgmFeature.parse(hex("0090")) }
    }
}
