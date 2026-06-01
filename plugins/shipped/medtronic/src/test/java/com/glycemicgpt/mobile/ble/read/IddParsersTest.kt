/*
 * AC1/AC5: IDD payload parsers (status / IOB / active-basal / features) decoded against the published
 * upstream PythonPumpConnector test vectors, the per-model feature tiering, and the optional Medtronic
 * E2E trailer. These vectors are the shared, published-upstream protocol examples from the modules'
 * __main__ blocks (not session secrets).
 */
package com.glycemicgpt.mobile.ble.read

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class IddParsersTest {

    @Test
    fun `IDD status parses the published vector`() {
        // pump_status.py: 5596e80d28fb010300
        val status = IddStatusRecord.parse(hex("5596e80d28fb010300"), useE2e = false)
        assertEquals(TherapyControlState.RUN, status.therapyControlState)
        assertEquals(OperationalState.READY, status.operationalState)
        assertEquals(26.25, status.reservoirRemainingIu, 1e-9)
        assertTrue(status.reservoirAttached)
        assertEquals(SensorMessageState.NO_MESSAGE, status.sensorMessageState)
    }

    @Test
    fun `IDD status validates and strips the E2E trailer when enabled`() {
        val body = hex("5596e80d28fb010300")
        val counter = byteArrayOf(0x01)
        val protectedPrefix = body + counter
        val crc = MedtronicCodec.e2eCrc(protectedPrefix)
        val withE2e = protectedPrefix + byteArrayOf((crc and 0xFF).toByte(), ((crc shr 8) and 0xFF).toByte())

        val status = IddStatusRecord.parse(withE2e, useE2e = true)
        assertEquals(TherapyControlState.RUN, status.therapyControlState)
        assertEquals(26.25, status.reservoirRemainingIu, 1e-9)
    }

    @Test
    fun `IDD status rejects a corrupt E2E-CRC`() {
        val withBadCrc = hex("5596e80d28fb010300") + hex("01dead")
        assertThrows(MedtronicReadException::class.java) {
            IddStatusRecord.parse(withBadCrc, useE2e = true)
        }
    }

    @Test
    fun `IDD status rejects a wrong-length body`() {
        assertThrows(MedtronicReadException::class.java) {
            IddStatusRecord.parse(hex("5596e80d28fb0103"), useE2e = false)
        }
    }

    @Test
    fun `IOB parses the published vector`() {
        // iob.py: fc0300c05c15fa
        val iob = IddInsulinOnBoard.parse(hex("fc0300c05c15fa"), useE2e = false)
        assertEquals(1.4, iob.insulinOnBoardIu, 1e-9)
        assertNull(iob.remainingDurationMin)
    }

    @Test
    fun `IOB rejects a wrong response opcode`() {
        assertThrows(MedtronicReadException::class.java) {
            IddInsulinOnBoard.parse(hex("0000" + "00" + "c05c15fa"), useE2e = false)
        }
    }

    @Test
    fun `active basal parses the published vector`() {
        // active_basal_rate_delivery.py: 6a03000200000000
        val basal = IddActiveBasalRate.parse(hex("6a03000200000000"), useE2e = false)
        assertEquals(0.0, basal.rateIuPerHour, 0.0)
        assertEquals(2, basal.templateNumber)
        assertNull(basal.basalDeliveryContext)
    }

    @Test
    fun `active basal reads an AP-controller delivery context`() {
        // opcode 036a, flags 0x04 (context present), template 0, rate 0, context 0x55 (AP controller).
        val basal = IddActiveBasalRate.parse(hex("6a0304000000000055"), useE2e = false)
        assertEquals(BasalDeliveryContext.AP_CONTROLLER, basal.basalDeliveryContext)
    }

    @Test
    fun `IDD features parses the published vector`() {
        // pump_features.py: ffff006400fede801f
        val features = IddFeatures.parse(hex("ffff006400fede801f"))
        assertEquals(100.0, features.insulinConcentration, 1e-6) // U-100 insulin
        assertFalse(features.e2eProtectionEnabled)
        // Real 700-series dump: closed loop supported. Assert the robust capability fact, not the exact
        // 770-vs-780 tier (that boundary is verified deterministically below with synthesized flags).
        assertTrue(features.model.supportsSmartGuard)
    }

    @Test
    fun `pump model tiers from the closed-loop feature bits`() {
        assertEquals(MedtronicPumpModel.UNKNOWN, MedtronicPumpModel.fromFeatureFlags(0L))
        assertEquals(MedtronicPumpModel.MINIMED_680G, MedtronicPumpModel.fromFeatureFlags(0x0000_0002L))
        assertEquals(MedtronicPumpModel.MINIMED_770G, MedtronicPumpModel.fromFeatureFlags(0x1000_0000L))
        assertEquals(MedtronicPumpModel.MINIMED_780G, MedtronicPumpModel.fromFeatureFlags(0x3000_0000L))
        assertFalse(MedtronicPumpModel.MINIMED_680G.supportsSmartGuard)
        assertTrue(MedtronicPumpModel.MINIMED_780G.supportsAutoCorrectionBolus)
        assertFalse(MedtronicPumpModel.MINIMED_770G.supportsAutoCorrectionBolus)
    }
}
