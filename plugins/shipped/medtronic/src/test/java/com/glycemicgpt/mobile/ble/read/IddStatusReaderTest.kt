/*
 * AC1/AC4: the IDD status reader drives the C1 framework end to end -- decrypts the encrypted IDD
 * Features + Status reads and the SRCP IOB/basal exchanges through a genuine two-sided SAKE session,
 * maps them to the shared domain models, and rejects (never clamps) out-of-range values.
 *
 * Inbound frames are encrypted in the order the reader decrypts them so the SAKE sequence counters
 * stay aligned (features read first, then the status read or the SRCP response).
 */
package com.glycemicgpt.mobile.ble.read

import com.glycemicgpt.mobile.ble.protocol.MedtronicProtocol
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class IddStatusReaderTest {

    private val features = MedtronicProtocol.IDD_FEATURES_UUID
    private val status = MedtronicProtocol.IDD_STATUS_UUID
    private val srcp = MedtronicProtocol.IDD_SRCP_UUID

    // E2E-disabled features (matches the published pump_features.py vector: e2e bit clear).
    private val featuresPlain = hex("ffff006400fede801f")

    @Test
    fun `readReservoir decrypts the status read and maps units remaining`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.reads[features] = two.pumpEncrypt(featuresPlain)
        link.reads[status] = two.pumpEncrypt(hex("5596e80d28fb010300"))

        var result: Result<com.glycemicgpt.mobile.domain.model.ReservoirReading>? = null
        IddStatusReader(link, two.server).readReservoir { result = it }

        assertEquals(26.25f, result!!.getOrThrow().unitsRemaining, 1e-3f)
    }

    @Test
    fun `readStatusState surfaces therapy, sensor and model`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.reads[features] = two.pumpEncrypt(featuresPlain)
        link.reads[status] = two.pumpEncrypt(hex("5596e80d28fb010300"))

        var result: Result<MedtronicIddStatusState>? = null
        IddStatusReader(link, two.server).readStatusState { result = it }

        val state = result!!.getOrThrow()
        assertEquals(TherapyControlState.RUN, state.therapyControlState)
        assertEquals(OperationalState.READY, state.operationalState)
        assertEquals(SensorMessageState.NO_MESSAGE, state.sensorMessageState)
        assertTrue(state.reservoirAttached)
        assertTrue(state.model.supportsSmartGuard)
    }

    @Test
    fun `readReservoir rejects an out-of-range reservoir`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.reads[features] = two.pumpEncrypt(featuresPlain)
        // reservoir medfloat32 9999 IU (0x0000270f) -> above the 300 IU hardware bound.
        link.reads[status] = two.pumpEncrypt(hex("55960f270000010300"))

        var result: Result<com.glycemicgpt.mobile.domain.model.ReservoirReading>? = null
        IddStatusReader(link, two.server).readReservoir { result = it }

        assertTrue(result!!.isFailure)
        assertTrue(result!!.exceptionOrNull() is MedtronicReadException)
    }

    @Test
    fun `readIoB decrypts the SRCP exchange and maps IOB`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.reads[features] = two.pumpEncrypt(featuresPlain)
        link.onWrite = { characteristic, _ ->
            if (characteristic == srcp) emit(srcp, two.pumpEncrypt(hex("fc0300c05c15fa")))
        }

        var result: Result<com.glycemicgpt.mobile.domain.model.IoBReading>? = null
        IddStatusReader(link, two.server).readIoB { result = it }

        assertEquals(1.4f, result!!.getOrThrow().iob, 1e-5f)
    }

    @Test
    fun `readIoB rejects an implausible provisional IOB`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.reads[features] = two.pumpEncrypt(featuresPlain)
        // IOB medfloat32 200 IU (0x000000c8) -> above the plausible ceiling.
        link.onWrite = { characteristic, _ ->
            if (characteristic == srcp) emit(srcp, two.pumpEncrypt(hex("fc0300c8000000")))
        }

        var result: Result<com.glycemicgpt.mobile.domain.model.IoBReading>? = null
        IddStatusReader(link, two.server).readIoB { result = it }

        assertTrue(result!!.isFailure)
    }

    @Test
    fun `readActiveBasalRate maps the rate and is manual without an AP context`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.reads[features] = two.pumpEncrypt(featuresPlain)
        link.onWrite = { characteristic, _ ->
            if (characteristic == srcp) emit(srcp, two.pumpEncrypt(hex("6a03000200000000")))
        }

        var result: Result<com.glycemicgpt.mobile.domain.model.BasalReading>? = null
        IddStatusReader(link, two.server).readActiveBasalRate { result = it }

        val basal = result!!.getOrThrow()
        assertEquals(0.0f, basal.rate, 0.0f)
        assertEquals(false, basal.isAutomated)
    }

    @Test
    fun `readActiveBasalRate rejects a basal rate over the safety limit`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.reads[features] = two.pumpEncrypt(featuresPlain)
        // rate medfloat32 20 IU/h (0x00000014) -> 20000 mU/h, above the 15000 mU/h default cap.
        link.onWrite = { characteristic, _ ->
            if (characteristic == srcp) emit(srcp, two.pumpEncrypt(hex("6a03000014000000")))
        }

        var result: Result<com.glycemicgpt.mobile.domain.model.BasalReading>? = null
        IddStatusReader(link, two.server, SafetyLimits()).readActiveBasalRate { result = it }

        assertTrue(result!!.isFailure)
    }
}
