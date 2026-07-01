/*
 * IDD status reader for the Medtronic MiniMed 700-series read-only driver.
 *
 * GlycemicGPT code (GPL-3.0). The read choreography -- read the IDD Features for the per-model E2E
 * flag, read+decrypt the IDD Status characteristic, and drive the SRCP control point for IOB and
 * active-basal opcodes -- is ported from OpenMinimed PythonPumpConnector `idd/status/reader.py`
 * (IDDStatusReader) and `idd/features/reader.py` (IDDFeaturesReader), GPL-3.0, used with the
 * author's permission. Copyright (C) OpenMinimed contributors: palmarci (Pal Marci), drfubar,
 * Morten Fyhn Amundsen, Stenium; original medtronic-bt-decrypt PoC by @planiitis. GlycemicGPT is
 * itself GPL-3.0. See medtronic-ble-reverse-engineering.md Sec. 8.
 */
package com.glycemicgpt.mobile.ble.read

import com.glycemicgpt.mobile.ble.protocol.MedtronicProtocol
import com.glycemicgpt.mobile.ble.sake.MedtronicSakeSession
import com.glycemicgpt.mobile.domain.model.BasalReading
import com.glycemicgpt.mobile.domain.model.IoBReading
import com.glycemicgpt.mobile.domain.model.PumpActivityMode
import com.glycemicgpt.mobile.domain.model.ReservoirReading
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import java.time.Instant
import kotlin.math.roundToInt
import timber.log.Timber

/**
 * The non-history IDD status surface bundled from one IDD Status read: therapy/operational state,
 * reservoir-attached flag, sensor state, and the inferred per-model capability tier.
 */
data class MedtronicIddStatusState(
    val therapyControlState: TherapyControlState,
    val operationalState: OperationalState,
    val reservoirAttached: Boolean,
    val sensorMessageState: SensorMessageState,
    val sensorConnectivityFlags: Int,
    val model: MedtronicPumpModel,
)

/**
 * Reads the pump's Insulin Delivery (IDD) status surface over the C1 session-read framework into the
 * shared domain models: reservoir ([ReservoirReading]), IOB ([IoBReading], **provisional**), active
 * basal ([BasalReading]) and the therapy/sensor [MedtronicIddStatusState].
 *
 * Every numeric value is gated by [safetyLimits]: an out-of-physiological-range reservoir/IOB/basal
 * is **rejected** (a [MedtronicReadException]), never clamped, matching [CgmReader]. Over-the-air
 * behavior rides with 48.A2; nothing here is claimed live-verified.
 *
 * The IDD Features read supplies two per-model facts (avoiding the upstream 780G hard-codes): the
 * E2E-protection flag (whether records carry the E2E trailer) and the SmartGuard capability tier
 * ([MedtronicPumpModel]). It is re-read per call for these single-shot reads; caching belongs with
 * polling in Milestone D (as on [CgmReader]).
 *
 * @param now clock for stamping "current" readings; report time approximates capture time for these
 *     live status reads.
 */
class IddStatusReader(
    private val link: MedtronicGattLink,
    session: MedtronicSakeSession,
    private val safetyLimits: SafetyLimits = SafetyLimits(),
    private val now: () -> Instant = Instant::now,
) {
    private val sessionReader = MedtronicSessionReader(link, session)

    /** Reservoir units remaining, gated by the reservoir hardware bound. */
    fun readReservoir(onResult: (Result<ReservoirReading>) -> Unit) {
        onResult(
            runCatching {
                val features = readFeatures()
                val status = readStatusRecord(features)
                toReservoirReading(status.reservoirRemainingIu)
            },
        )
    }

    /** Therapy/operational/sensor state plus the inferred model tier. */
    fun readStatusState(onResult: (Result<MedtronicIddStatusState>) -> Unit) {
        onResult(
            runCatching {
                val features = readFeatures()
                val status = readStatusRecord(features)
                MedtronicIddStatusState(
                    therapyControlState = status.therapyControlState,
                    operationalState = status.operationalState,
                    reservoirAttached = status.reservoirAttached,
                    sensorMessageState = status.sensorMessageState,
                    sensorConnectivityFlags = status.sensorConnectivityFlags,
                    model = features.model,
                )
            },
        )
    }

    /**
     * Active insulin on board.
     *
     * ⚠️ **PROVISIONAL** -- upstream marks IOB parsing "not tested" (`iob.py`). It is parsed faithfully
     * and safety-gated, but emitted with a warning marker and **must not be presented as trusted**
     * until a live pump confirms the layout. `TODO(48.A2)`.
     */
    fun readIoB(onResult: (Result<IoBReading>) -> Unit) {
        val features =
            try {
                readFeatures()
            } catch (e: MedtronicReadException) {
                onResult(Result.failure(e))
                return
            }
        sessionReader.srcpGet(MedtronicProtocol.IDD_SRCP_UUID, REQUEST_GET_INSULIN_ON_BOARD) { result ->
            onResult(result.mapCatching { decrypted -> toIoBReading(decrypted, features.e2eProtectionEnabled) })
        }
    }

    /** Active basal rate currently being delivered, with automated (closed-loop) detection. */
    fun readActiveBasalRate(onResult: (Result<BasalReading>) -> Unit) {
        val features =
            try {
                readFeatures()
            } catch (e: MedtronicReadException) {
                onResult(Result.failure(e))
                return
            }
        sessionReader.srcpGet(MedtronicProtocol.IDD_SRCP_UUID, REQUEST_GET_ACTIVE_BASAL_RATE) { result ->
            onResult(result.mapCatching { decrypted -> toBasalReading(decrypted, features) })
        }
    }

    private fun readFeatures(): IddFeatures =
        IddFeatures.parse(sessionReader.decryptedRead(MedtronicProtocol.IDD_FEATURES_UUID))

    private fun readStatusRecord(features: IddFeatures): IddStatusRecord =
        IddStatusRecord.parse(
            sessionReader.decryptedRead(MedtronicProtocol.IDD_STATUS_UUID),
            features.e2eProtectionEnabled,
        )

    private fun toReservoirReading(reservoirIu: Double): ReservoirReading {
        if (!reservoirIu.isFinite() || reservoirIu < 0.0 || reservoirIu > MAX_RESERVOIR_UNITS) {
            throw MedtronicReadException(
                "Reservoir $reservoirIu IU outside safe range 0..$MAX_RESERVOIR_UNITS",
            )
        }
        return ReservoirReading(unitsRemaining = reservoirIu.toFloat(), timestamp = now())
    }

    private fun toIoBReading(decrypted: ByteArray, useE2e: Boolean): IoBReading {
        val iob = IddInsulinOnBoard.parse(decrypted, useE2e).insulinOnBoardIu
        if (!iob.isFinite() || iob < 0.0 || iob > MAX_IOB_UNITS) {
            throw MedtronicReadException("IOB $iob IU outside plausible range 0..$MAX_IOB_UNITS")
        }
        return IoBReading(iob = iob.toFloat(), timestamp = now())
    }

    private fun toBasalReading(decrypted: ByteArray, features: IddFeatures): BasalReading {
        val parsed = IddActiveBasalRate.parse(decrypted, features.e2eProtectionEnabled)
        val rate = parsed.rateIuPerHour
        if (!rate.isFinite() || rate < 0.0) {
            throw MedtronicReadException("Basal rate $rate IU/h is not a valid non-negative number")
        }
        val milliunits = (rate * 1000.0).roundToInt()
        if (milliunits > safetyLimits.maxBasalRateMilliunits) {
            throw MedtronicReadException(
                "Basal rate $rate IU/h ($milliunits mU/h) exceeds safe max ${safetyLimits.maxBasalRateMilliunits} mU/h",
            )
        }
        // Closed-loop (SmartGuard) delivery is reported via the AP-controller basal context, which the
        // 680G never sets. Treat an AP-controller context as automated; flag the model mismatch if a
        // non-SmartGuard tier somehow reports it (data-shape sanity per AC5, not a hard failure).
        val automated = parsed.basalDeliveryContext == BasalDeliveryContext.AP_CONTROLLER
        if (automated && !features.model.supportsSmartGuard) {
            Timber.w(
                "AP-controller basal context on a non-SmartGuard tier (%s); treating as automated",
                features.model,
            )
        }
        return BasalReading(
            rate = rate.toFloat(),
            isAutomated = automated,
            activityMode = PumpActivityMode.NONE, // pump activity mode is not in the IDD basal payload
            timestamp = now(),
        )
    }

    companion object {
        // SRCP request opcodes, little-endian (idd/status/opcodes.py IddStatusReaderOpCode).
        private val REQUEST_GET_INSULIN_ON_BOARD = byteArrayOf(0xF3.toByte(), 0x03) // 0x03F3
        private val REQUEST_GET_ACTIVE_BASAL_RATE = byteArrayOf(0x65, 0x03) // 0x0365

        /** 700-series reservoir hardware maximum (IU); a reading above this is rejected, not clamped. */
        const val MAX_RESERVOIR_UNITS = 300.0

        /**
         * Plausible upper bound on insulin-on-board (IU). Real IOB rarely exceeds the low tens of
         * units; this generous ceiling rejects a garbled/misaligned PROVISIONAL IOB read rather than
         * surfacing a wrong value. `TODO(48.A2)`: revisit once IOB is validated on a real pump.
         */
        const val MAX_IOB_UNITS = 100.0
    }
}
